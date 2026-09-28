#!/usr/bin/env python3
"""A sourced statement-date override replaces the upload date, everywhere, or nowhere.

Why this exists (VP-16, docs/LEDGER-predictions.md). A YouTube upload date stands
in for the date of speech. On an old recording that manufactures a wrong
deadline: Netscape's 2nd Internet Developer Conference keynote, given on
1996-10-16 and uploaded on 2013-07-05, became "Netscape will create a network of
online marketplaces by approximately September 2013". The claim text itself
carries the wrong year, so the fix cannot be a date swap on the record. The
transcript is re-extracted under the true date.

What this pins:
  1. The override file refuses an unknown transcript, a malformed date, a date
     AFTER the transcript's own upload or publication date, a missing field and an
     unknown field. Nothing is silently ignored.
  2. The override applies at ONE point, when a transcript is read for
     extraction. The statement date, its basis, the prompt header and the
     record all agree, and the record says the date came from an override.
  3. A transcript with no override is byte-identical to before: same date, same
     basis, same prompt header.
  4. The funnel supersedes a record extracted under the old date, whether the
     re-extracted record kept the same prediction_id or got a new one, and
     reports it. Andreessen is never counted twice.
  5. The scorer drops sidecars priced or resolved under the old date, names them,
     and hashes the override file into its inputs.
"""
from __future__ import annotations

import copy
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
sys.path.insert(0, str(ROOT / "scripts"))
import predictions_lib as L  # noqa: E402

FAILED: list[str] = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def raises(label, fn, *needles):
    try:
        fn()
    except (L.PredictionError, SystemExit, ValueError) as exc:
        msg = str(exc)
        check(label, all(n in msg for n in needles), f"message lacks {needles}: {msg[:300]}")
        return
    check(label, False, "no exception raised")


TID = "ada/talk1"
TEXT = ("[00:00:01] good morning and welcome [00:01:00] in the next couple months we are going to "
        "create a network of online market places for everyone")
TRANSCRIPT = {"leader_slug": "ada", "source_id": "talk1", "yt_upload_date": "20130705", "url": "u",
              "video_id": "v", "yt_title": "Keynote (New York 1996)", "declared_venue": "chan",
              "declared_kind": "keynote", "declared_year": 2013, "word_count": 20, "duration_sec": 600,
              "text": TEXT}
ENTRY = {"statement_date": "1996-10-16",
         "basis": "Opening keynote, Netscape 2nd Internet Developer Conference, 1996-10-16",
         "source_url": "http://web.archive.org/web/19970613214614/http://home.netscape.com/newsref/pr/newsrelease254.html",
         "verbatim_evidence": "being held October 16 through 18 at the New York Hilton and Towers",
         "confirmed_by": "operator", "confirmed_at_utc": "2026-09-28T05:19:02Z"}
ROSTER = {"name": "Ada L", "role": "CEO", "company": "Co", "sector": "AI"}


def write_fixture(d: pathlib.Path, overrides: dict, transcripts: dict | None = None) -> tuple[pathlib.Path, list]:
    troot = d / "transcripts_web"
    for tid, rec in (transcripts or {TID: TRANSCRIPT}).items():
        slug, sid = tid.split("/")
        (troot / slug).mkdir(parents=True, exist_ok=True)
        (troot / slug / f"{sid}.json").write_text(json.dumps(rec))
    path = d / "overrides.json"
    path.write_text(json.dumps({"schema_version": 1, "overrides": overrides}))
    return path, [troot]


def cand(quote):
    return {"quote": quote, "timestamp_hint": "[00:01:00]",
            "normalized_claim": "Netscape will create a network of online marketplaces by December 1996.",
            "gates": {g: True for g in L.GATES}, "gate_notes": "",
            "resolution_criteria": "By 1996-12-31, Netscape has launched a network of online marketplaces.",
            "category": "company_business", "prediction_type": "binary_event", "target_date": "1996-12",
            "target_date_text": "the next couple months", "horizon": "explicit", "horizon_years_inferred": None,
            "horizon_evidence": None, "specificity": "medium", "subject_control": "own",
            "confidence": {"type": "none", "probability": None, "verbatim_confidence_language": None}}


def test_loader(d: pathlib.Path) -> dict:
    print("LOADER: the override file refuses what it cannot vouch for")
    path, roots = write_fixture(d / "ok", {TID: ENTRY})
    ov = L.load_statement_date_overrides(path, roots)
    check("a valid entry loads, keyed by transcript id", list(ov) == [TID] and ov[TID]["statement_date"] == "1996-10-16",
          str(ov)[:200])

    def bad(name, overrides, *needles, transcripts=None):
        p, r = write_fixture(d / name, overrides, transcripts)
        raises(f"refuses {name}", lambda: L.load_statement_date_overrides(p, r), *needles)

    bad("an unknown transcript id", {"ada/nosuch": ENTRY}, "ada/nosuch", "unknown transcript")
    bad("a malformed date", {TID: {**ENTRY, "statement_date": "1996/10/16"}}, "1996/10/16")
    bad("an impossible date", {TID: {**ENTRY, "statement_date": "1996-02-30"}}, "1996-02-30")
    bad("a date after the upload date", {TID: {**ENTRY, "statement_date": "2013-07-06"}},
        "2013-07-06", "2013-07-05", "after")
    bad("a missing source_url", {TID: {k: v for k, v in ENTRY.items() if k != "source_url"}}, "source_url")
    bad("a missing confirmation", {TID: {k: v for k, v in ENTRY.items() if k != "confirmed_by"}}, "confirmed_by")
    bad("an empty verbatim_evidence", {TID: {**ENTRY, "verbatim_evidence": "  "}}, "verbatim_evidence")
    bad("an unknown field", {TID: {**ENTRY, "deadline": "1996-12-31"}}, "deadline")
    bad("a malformed confirmed_at_utc", {TID: {**ENTRY, "confirmed_at_utc": "2026-09-28"}}, "confirmed_at_utc")
    bad("a transcript id that is not slug/source", {"ada": ENTRY}, "slug/source")
    stated = {**TRANSCRIPT, "statement_date": "1996-10-16", "statement_date_basis": "stated_in_page"}
    stated.pop("yt_upload_date")
    bad("an override of a page that states its own date", {TID: ENTRY}, "stated_in_page",
        transcripts={TID: stated})
    p, r = write_fixture(d / "wrongshape", {})
    p.write_text(json.dumps({TID: ENTRY}))
    raises("refuses a file without schema_version and overrides", lambda: L.load_statement_date_overrides(p, r),
           "schema_version")

    same_day, r2 = write_fixture(d / "sameday", {TID: {**ENTRY, "statement_date": "2013-07-05"}})
    check("an override ON the upload date is allowed (same day, not after)",
          L.load_statement_date_overrides(same_day, r2)[TID]["statement_date"] == "2013-07-05")
    undated = {k: v for k, v in TRANSCRIPT.items() if k != "yt_upload_date"}
    p3, r3 = write_fixture(d / "undated", {TID: ENTRY}, {TID: undated})
    check("a transcript with no date of its own accepts an override (no upper bound to check)",
          TID in L.load_statement_date_overrides(p3, r3))
    return ov


def test_apply(ov: dict) -> None:
    print("APPLY: one point of entry, and everything downstream agrees")
    plain = copy.deepcopy(TRANSCRIPT)
    check("no override: date and basis unchanged",
          L.derive_statement_date(plain) == ("2013-07-05", "youtube_upload_date"))
    header_before = L.speaker_header(plain, ROSTER)
    check("no override: the prompt header is the old one, byte for byte",
          "Statement date: 2013-07-05 (YouTube upload date; the recording is no later than this)\n" in header_before)
    other = {**TRANSCRIPT, "source_id": "talk2"}
    check("apply leaves a transcript without an entry as the same object",
          L.apply_statement_date_override(other, ov) is other)

    rec = L.apply_statement_date_override(copy.deepcopy(TRANSCRIPT), ov)
    check("override: derive_statement_date returns the override date and its own basis",
          L.derive_statement_date(rec) == ("1996-10-16", L.OVERRIDE_DATE_BASIS), str(L.derive_statement_date(rec)))
    check("override: the basis is not youtube_upload_date", L.OVERRIDE_DATE_BASIS != "youtube_upload_date")
    h = L.speaker_header(rec, ROSTER)
    check("override: the prompt header states 1996-10-16 as the statement date",
          "Statement date: 1996-10-16 (" in h, h)
    check("override: the header says the upload date is later and is not the date of speech",
          "2013-07-05" in h and "NOT" in h and "YouTube upload date; the recording is no later than this" not in h, h)
    check("override: the header differs from the non-override header only on the date line",
          [x for x in h.splitlines() if not x.startswith("Statement date:")]
          == [x for x in header_before.splitlines() if not x.startswith("Statement date:")])
    tampered = {**rec, "statement_date_override": {**rec["statement_date_override"], "statement_date": "2014-01-01"}}
    raises("derive refuses an applied override dated after the upload (defence in depth)",
           lambda: L.derive_statement_date(tampered), "2014-01-01", "after")

    loc = L.locate_quote(TEXT, "in the next couple months we are going to create a network of online market places")
    prov = L.normalise_provenance("astra", {"requested_model": "gpt-6-astra", "served_model": "gpt-6-astra"}, None, "codex")
    r = L.make_record(rec, ROSTER, cand("in the next couple months we are going to create a network of online market places"),
                      loc, prov, "c" * 12, "run", "2026-09-28T00:00:00Z", {})
    src = r["source"]
    check("record: statement_date is the override date", src["statement_date"] == "1996-10-16")
    check("record: statement_date_basis names the override", src["statement_date_basis"] == L.OVERRIDE_DATE_BASIS)
    blk = src.get("statement_date_override") or {}
    check("record: the override block carries basis, source, evidence, confirmation and what it replaced",
          blk.get("basis") == ENTRY["basis"] and blk.get("source_url") == ENTRY["source_url"]
          and blk.get("verbatim_evidence") == ENTRY["verbatim_evidence"] and blk.get("confirmed_by") == "operator"
          and blk.get("confirmed_at_utc") == ENTRY["confirmed_at_utc"]
          and blk.get("replaced_date") == "2013-07-05" and blk.get("replaced_basis") == "youtube_upload_date", str(blk))
    errs = L.check_schema(r, L.load_record_schema())
    check("record: an overridden record validates against the record schema", errs == [], str(errs)[:300])
    r_plain = L.make_record(plain, ROSTER, cand("in the next couple months we are going to create a network of online market places"),
                            loc, prov, "c" * 12, "run", "2026-09-28T00:00:00Z", {})
    check("record: a non-overridden record carries no override block", "statement_date_override" not in r_plain["source"])
    check("record: the prediction_id is a function of transcript and quote, so it survives the override",
          r["prediction_id"] == r_plain["prediction_id"])
    test_validator(r, r_plain)

    import extract_predictions as D
    with tempfile.TemporaryDirectory() as td:
        tp = pathlib.Path(td) / "ada" / "talk1.json"
        tp.parent.mkdir(parents=True)
        tp.write_text(json.dumps(TRANSCRIPT))
        got = D.read_transcript(tp, TID, ov)
        check("extraction: read_transcript applies the override on load",
              L.derive_statement_date(got) == ("1996-10-16", L.OVERRIDE_DATE_BASIS))
        check("extraction: read_transcript without overrides is unchanged",
              L.derive_statement_date(D.read_transcript(tp, TID)) == ("2013-07-05", "youtube_upload_date"))
        spec = L.read_spec(L.SKILL / L.EXTRACTION_SPEC)
        p = L.build_extraction_prompt(got, ROSTER, spec, "{}")
        check("extraction: the prompt the extractor sees states 1996-10-16", "Statement date: 1996-10-16 (" in p)
        check("extraction: the input hash differs, so a cached extraction under the old date is stale",
              L.json_sha256({"transcript": got}) != L.json_sha256({"transcript": D.read_transcript(tp, TID)}))


def record(pid, date, basis, block=None, tid=TID):
    src = {"statement_date": date, "statement_date_basis": basis, "quote": "q"}
    if block:
        src["statement_date_override"] = block
    return {"accepted": True, "leader_slug": "ada", "prediction_id": pid, "transcript_id": tid,
            "prediction": {"target_date": "1996-12" if basis == L.OVERRIDE_DATE_BASIS else "2013-09",
                           "specificity": "medium", "subject_control": "own", "category": "company_business",
                           "horizon": "explicit", "target_date_text": "the next couple months",
                           "horizon_years_inferred": None, "prediction_type": "binary_event",
                           "normalized_claim": "c", "resolution_criteria": "crit"},
            "source": src, "confidence": {"probability": None},
            "consensus": {"status": "no_match", "exact_match": None}}


def other_record(pid):
    r = record(pid, "2019-01-01", "youtube_upload_date", tid="ada/other")
    r["prediction"]["target_date"] = "2020-12-31"
    return r


def write_corpus(d: pathlib.Path, name: str, recs: list[dict]) -> pathlib.Path:
    c = d / name
    by: dict[str, list] = {}
    for r in recs:
        by.setdefault(r["transcript_id"], []).append(r)
    for tid, rs in by.items():
        slug, sid = tid.split("/")
        (c / slug).mkdir(parents=True, exist_ok=True)
        (c / slug / f"{sid}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rs))
    return c


def test_funnel(d: pathlib.Path, ov: dict) -> None:
    print("FUNNEL: a record extracted under the old date is superseded, never counted twice")
    import phase2_resolvability as P2
    from resolve_predictions import select
    import datetime as dt
    block = {"basis": ENTRY["basis"], "source_url": ENTRY["source_url"], "verbatim_evidence": ENTRY["verbatim_evidence"],
             "confirmed_by": "operator", "confirmed_at_utc": ENTRY["confirmed_at_utc"],
             "replaced_date": "2013-07-05", "replaced_basis": "youtube_upload_date"}
    prod = write_corpus(d, "prod", [record("OLDPID", "2013-07-05", "youtube_upload_date"), other_record("KEEP")])

    same = write_corpus(d, "rerun-same", [record("OLDPID", "1996-10-16", L.OVERRIDE_DATE_BASIS, block)])
    raises("without the override file, the same pid in two corpora is still refused as a duplicate",
           lambda: P2.load([prod, same]), "OLDPID")
    sup: list = []
    rows = P2.load([prod, same], date_overrides=ov, superseded=sup)
    ids = sorted((r["prediction_id"], r["source"]["statement_date"]) for r in rows)
    check("SAME PID: the re-extracted record is kept and the stale one superseded",
          ids == [("KEEP", "2019-01-01"), ("OLDPID", "1996-10-16")], str(ids))
    check("SAME PID: the superseded record is reported with its old date and the override date",
          len(sup) == 1 and sup[0]["prediction_id"] == "OLDPID" and sup[0]["statement_date"] == "2013-07-05"
          and sup[0]["override_date"] == "1996-10-16", str(sup))

    new = write_corpus(d, "rerun-new", [record("NEWPID", "1996-10-16", L.OVERRIDE_DATE_BASIS, block)])
    sup = []
    rows = P2.load([prod, new], date_overrides=ov, superseded=sup)
    ids = sorted(r["prediction_id"] for r in rows)
    check("NEW PID: only the re-extracted record survives from the overridden transcript",
          ids == ["KEEP", "NEWPID"], str(ids))
    check("NEW PID: the old prediction is reported as superseded", [s["prediction_id"] for s in sup] == ["OLDPID"])

    sup = []
    rows = P2.load([prod], date_overrides=ov, superseded=sup)
    check("NOT YET RE-EXTRACTED: the stale record is superseded rather than scored under the wrong date",
          sorted(r["prediction_id"] for r in rows) == ["KEEP"] and len(sup) == 1)

    sup = []
    rows = P2.load([prod, new], date_overrides={}, superseded=sup)
    check("WITHDRAWN OVERRIDE: a record carrying an override the file no longer holds is superseded",
          "NEWPID" not in [r["prediction_id"] for r in rows] and "NEWPID" in [s["prediction_id"] for s in sup])

    sel = select([prod, new], dt.date(2026, 9, 27), 60, trend=True, date_overrides=ov)
    got = {r["prediction_id"]: r for r in sel}
    check("SELECT: resolve/score selection sees the new record once, past due, eligible, with a 1996 deadline",
          "OLDPID" not in got and got.get("NEWPID", {}).get("_deadline") == dt.date(1996, 12, 31)
          and got["NEWPID"]["_flags"]["eligible"] is True and got["NEWPID"]["_flags"]["lead_days"] == 76,
          str({k: (v["_deadline"], v["_flags"]) for k, v in got.items()}))


def test_sidecars_and_scorer(d: pathlib.Path) -> None:
    print("SCORER: old-date sidecars are dropped and named; the override file is an input")
    import resolution_lib as R
    import datetime as dt
    block = {"basis": ENTRY["basis"], "source_url": ENTRY["source_url"], "verbatim_evidence": ENTRY["verbatim_evidence"],
             "confirmed_by": "operator", "confirmed_at_utc": ENTRY["confirmed_at_utc"],
             "replaced_date": "2013-07-05", "replaced_basis": "youtube_upload_date"}
    new_rec = record("NEWPID", "1996-10-16", L.OVERRIDE_DATE_BASIS, block)
    res = R.resolution_record(new_rec, dt.date(1996, 12, 31),
                              {"outcome": "not_occurred", "confidence": "high", "sources": [], "unresolvable_reason": None,
                               "reasoning": "r"}, run_id="r", harness="astra", account="codex", telemetry={},
                              resolved_at="2026-09-28T00:00:00Z", as_of="2026-09-27")
    pri = R.prior_record(new_rec, dt.date(1996, 12, 31), {"p": 0.3, "reference_class": "rc", "reasoning": "r"},
                         run_id="r", harness="fable", account="default", telemetry={},
                         assessed_at="2026-09-28T00:00:00Z", prompt_sha="x", leaks=[])
    check("SIDECARS: a new resolution records the statement date it was resolved against",
          res.get("statement_date") == "1996-10-16" and res.get("statement_date_basis") == L.OVERRIDE_DATE_BASIS)
    check("SIDECARS: a new prior records the statement date it was priced at",
          pri.get("statement_date") == "1996-10-16" and pri.get("statement_date_basis") == L.OVERRIDE_DATE_BASIS)

    data = d / "data"
    path, roots = write_fixture(data, {TID: ENTRY})
    ov_file = data / "predictions" / "_experiments" / "run-new" / "statement_date_overrides.json"
    ov_file.parent.mkdir(parents=True)
    ov_file.write_text(path.read_text())
    corpus = write_corpus(data, "predictions", [record("OLDPID", "2013-07-05", "youtube_upload_date"), other_record("KEEP")])
    rerun = write_corpus(data / "predictions" / "_experiments" / "run-new", "results",
                         [record("OLDPID", "1996-10-16", L.OVERRIDE_DATE_BASIS, block)])
    index = data / "predictions" / "index.json"
    index.write_text(json.dumps({"leaders": [{"slug": "ada", "name": "Ada L"}]}))
    old_run, new_run = data / "predictions" / "_experiments" / "run-old", data / "predictions" / "_experiments" / "run-new"

    def sidecar(run, pid, tid, stage, **extra):
        base = {"prediction_id": pid, "leader_slug": "ada", "transcript_id": tid, "stage": stage}
        if stage == "resolve":
            base.update(outcome=extra.pop("outcome"), confidence="high", unresolvable_reason=extra.pop("reason", None),
                        reasoning="r", sources=[{"where": "u", "what_it_shows": "w", "date": None}], deadline="x")
        else:
            base.update(p=extra.pop("p"), p_raw=0.5, clamped=False, reference_class="rc", reasoning="r")
        base.update(extra)
        fp = R.sidecar_path(run, stage, "ada", pid)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(base))

    # The old run resolved and priced the stale record under 2013 (no statement_date field, as today).
    sidecar(old_run, "OLDPID", TID, "resolve", outcome="unresolvable", reason="deadline_incoherent")
    sidecar(old_run, "OLDPID", TID, "prior", p=0.03)
    sidecar(old_run, "KEEP", "ada/other", "resolve", outcome="occurred")
    sidecar(old_run, "KEEP", "ada/other", "prior", p=0.5)
    # The new run resolved and priced the re-extracted record under 1996.
    sidecar(new_run, "OLDPID", TID, "resolve", outcome="not_occurred", statement_date="1996-10-16")
    sidecar(new_run, "OLDPID", TID, "prior", p=0.3, statement_date="1996-10-16")

    def score(*extra, out):
        argv = [sys.executable, str(ROOT / "scripts" / "score_predictions.py"), "--predictions", str(corpus),
                "--predictions", str(rerun), "--index", str(index), "--as-of", "2026-09-27", "--trend",
                "--run", str(old_run), "--run", str(new_run), "--out", str(out), *extra]
        return subprocess.run(argv, capture_output=True, text=True)

    plain = score(out=data / "plain.json")
    check("SCORER: without the override the same pid in two corpora is refused, as before",
          plain.returncode != 0 and "OLDPID" in (plain.stderr + plain.stdout), plain.stderr[-400:])
    ok = score("--date-overrides", str(ov_file), out=data / "ov.json")
    check("SCORER: with the override it exits 0", ok.returncode == 0, ok.stderr[-800:])
    doc = json.loads((data / "ov.json").read_text()) if ok.returncode == 0 else {}
    preds = {p["prediction_id"]: p for p in doc.get("predictions", [])}
    check("SCORER: the overridden prediction scores once, on the 1996 date, from the new run's sidecars",
          list(preds).count("OLDPID") == 1 and preds.get("OLDPID", {}).get("statement_date") == "1996-10-16"
          and preds["OLDPID"]["scored"] is True and preds["OLDPID"]["p"] == 0.3
          and preds["OLDPID"]["outcome"] == "not_occurred", str(preds.get("OLDPID"))[:400])
    lead = next((l for l in doc.get("leaders", []) if l["slug"] == "ada"), {})
    check("SCORER: the person's n_scored counts it once", lead.get("n_scored") == 2, str(lead))
    rep = doc.get("date_overrides") or {}
    check("SCORER: the override file is named, relative to the data root",
          rep.get("file") == "predictions/_experiments/run-new/statement_date_overrides.json", str(rep)[:300])
    check("SCORER: the superseded record is named",
          [s["prediction_id"] for s in rep.get("superseded_records", [])] == ["OLDPID"], str(rep)[:400])
    dropped = sorted((s["prediction_id"], s["stage"], s["run"]) for s in rep.get("stale_sidecars_dropped", []))
    check("SCORER: both old-date sidecars are dropped and named with their run",
          dropped == [("OLDPID", "prior", "predictions/_experiments/run-old"),
                      ("OLDPID", "resolve", "predictions/_experiments/run-old")], str(dropped))
    check("SCORER: the override file is part of the recorded settings",
          doc.get("settings", {}).get("date_overrides") == "predictions/_experiments/run-new/statement_date_overrides.json")
    h1 = doc.get("inputs_sha256")
    ov_file.write_text(json.dumps({"schema_version": 1, "overrides": {TID: {**ENTRY, "confirmed_by": "someone else"}}}))
    ok2 = score("--date-overrides", str(ov_file), out=data / "ov2.json")
    h2 = json.loads((data / "ov2.json").read_text()).get("inputs_sha256") if ok2.returncode == 0 else None
    check("SCORER: editing the override file changes inputs_sha256", h1 and h2 and h1 != h2, f"{h1} {h2}")

    # The production default: a file at <data>/predictions/statement_date_overrides.json is never
    # silently ignored. It lives under predictions/ because ownership.json makes that path shared,
    # so a contributor clone can commit it; sources/ is daemon-only (2026-09-28).
    check("DEFAULT: the production override file lives under predictions/, a path every clone may write",
          L.DATE_OVERRIDES_FILE == pathlib.Path("predictions") / "statement_date_overrides.json", str(L.DATE_OVERRIDES_FILE))
    prod_ov = data / "predictions" / "statement_date_overrides.json"
    prod_ov.write_text(path.read_text())
    auto = score(out=data / "auto.json")
    auto_doc = json.loads((data / "auto.json").read_text()) if auto.returncode == 0 else {}
    check("SCORER: with no flag, the production override file is read, not ignored",
          auto.returncode == 0 and auto_doc.get("settings", {}).get("date_overrides") == "predictions/statement_date_overrides.json",
          auto.stderr[-400:])
    cfg = data / "predictions" / "scoring.json"
    cfg.write_text(json.dumps({"as_of": "2026-09-27", "trend": True, "min_lead_days": 60,
                               "predictions": ["predictions", "predictions/_experiments/run-new/results"],
                               "runs": ["predictions/_experiments/run-old", "predictions/_experiments/run-new"],
                               "index": "predictions/index.json", "out": "predictions/scores.json"}))
    no_key = subprocess.run([sys.executable, str(ROOT / "scripts" / "score_predictions.py"), "--config", str(cfg)],
                            capture_output=True, text=True)
    check("CONFIG: a scoring config that omits date_overrides while the production file exists is refused",
          no_key.returncode != 0 and "date_overrides" in (no_key.stderr + no_key.stdout), no_key.stderr[-400:])
    cfg.write_text(json.dumps({**json.loads(cfg.read_text()), "date_overrides": "predictions/statement_date_overrides.json"}))
    with_key = subprocess.run([sys.executable, str(ROOT / "scripts" / "score_predictions.py"), "--config", str(cfg)],
                              capture_output=True, text=True)
    check("CONFIG: a scoring config naming date_overrides scores", with_key.returncode == 0, with_key.stderr[-400:])
    from data_clone_workflow import scores_staleness
    check("CONFIG: scores computed from that config are fresh",
          with_key.returncode == 0 and scores_staleness(data / "predictions" / "scores.json", cfg) is None)
    prod_ov.write_text(json.dumps({"schema_version": 1, "overrides": {TID: {**ENTRY, "basis": "revised"}}}))
    check("CONFIG: editing the override file makes those scores stale",
          with_key.returncode == 0 and scores_staleness(data / "predictions" / "scores.json", cfg) is not None)


def test_validator(r: dict, r_plain: dict) -> None:
    print("VALIDATOR: the basis and the override block travel together")
    import validate_predictions as V
    schema = L.load_record_schema()

    def date_failures(rec):
        out: list = []
        V.check_record(rec, TEXT, pathlib.Path("x/ada/talk1.jsonl"), 1, {}, schema, {"c" * 12}, out)
        return [f for f in out if f["invariant"] in ("statement_date", "schema")]

    check("an overridden record passes the date checks", date_failures(r) == [], str(date_failures(r))[:300])
    check("a non-overridden record passes the date checks", date_failures(r_plain) == [], str(date_failures(r_plain))[:300])
    stripped = copy.deepcopy(r)
    del stripped["source"]["statement_date_override"]
    check("an override basis with no override block fails statement_date",
          any(f["invariant"] == "statement_date" for f in date_failures(stripped)), str(date_failures(stripped))[:300])
    grafted = copy.deepcopy(r_plain)
    grafted["source"]["statement_date_override"] = copy.deepcopy(r["source"]["statement_date_override"])
    check("an override block under the upload-date basis fails statement_date",
          any(f["invariant"] == "statement_date" for f in date_failures(grafted)), str(date_failures(grafted))[:300])


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        ov = test_loader(d / "loader")
        test_apply(ov)
        test_funnel(d / "funnel", ov)
        test_sidecars_and_scorer(d / "scorer")
    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 -- a missing function is a failing test, not a crash to read
        print(f"FAIL  the test could not run: {type(exc).__name__}: {exc}")
        sys.exit(1)
