#!/usr/bin/env python3
"""A Happy Scribe record keeps the page's own date and decodes its own text.

WHY THIS EXISTS. FOUND 2026-09-28 in the predictions rescue (design section 1.3,
eval S1). Every Happy Scribe transcript in the corpus shows "date unknown" on
the predictions page, and 18 accepted records sit undated and unchecked because
of it. The date was on the page the fetcher read: the same JSON-LD BlogPosting
whose `associatedMedia.transcript` is the transcript carries
`"datePublished": "2025-09-17T23:05:00+02:00"`, and `page_meta` kept only the
title and description. The same page taught a second defect. The JSON path
decoded the JSON string but never HTML-unescaped it, so "we&#39;re" reached the
corpus, the extractor's quotes and the published cards. Only the HTML fallback
path unescaped.

Both fixes apply to FUTURE fetches only. Existing transcripts are daemon-owned
files that nothing here rewrites, and the CACHED check pins that.

  TEXT        the JSON transcript path returns decoded text, and the timestamps
              prove it was the JSON path and not the HTML fallback
  DATE        statement_date is the UTC date of JSON-LD datePublished, with basis
              publication_date, and predictions_lib reads the pair as declared
  UTC         the UTC date, not the page's local date, in both directions. The
              test runs in Asia/Tokyo, so a local-clock regression fails on a
              UTC machine too
  OWNER       only the one JSON-LD object that carries the transcript dates it.
              A date on a nested or another entity is evidence, never the date
  NODATE      no datePublished gives no statement_date key and no basis key; the
              fetch time is never a stand-in
  NULL        a JSON null datePublished is the same as no datePublished
  OUTSIDE     a page that names "datePublished" outside the JSON-LD this fetcher
              reads, with no date inside it, is not written as silently undated
  UNREADABLE  a date the fetcher cannot read keeps the transcript, because the
              leaders board uses it and never reads the date. The record has no
              statement_date and says why in hs_date_unreadable
  FUTURE      a publication date after the UTC date of the record's own
              fetched_at_utc is unreadable
  SUMMARY     the real main() counts and names records written without a date
  YEAR        declared_year stays 0, and the leaders judge prompt is byte-identical
              with and without the new fields
  CACHED      an already-fetched file is never rewritten
  MARKER      a new record says its text is already unescaped, so a later
              read-time view (design section 4.5) does not unescape it twice

The fixture is a synthetic page shaped like the archived one, under
scripts/fixtures/happyscribe/. No network, no quota, no data/.

  .venv/bin/python scripts/test_hs_fetch_record.py
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import fetch_happyscribe as F  # noqa: E402
import predictions_lib as L  # noqa: E402

FIXTURE = REPO / "scripts" / "fixtures" / "happyscribe" / "episode_page.html"
PAGE = FIXTURE.read_text(encoding="utf-8")
DATE_LINE = '"datePublished": "2025-09-17T23:05:00+02:00",'
# Exact substrings of the fixture that the twins below edit. twin() refuses one
# that does not occur exactly once, so a fixture edit cannot quietly turn a twin
# into a copy of the fixture.
EPISODE_NAME = '"name": "Idris Okonkwo on grid batteries, patient capital &amp; why we&#39;re early",'
SERIES = '"partOfSeries": {"@type": "PodcastSeries", "name": "The Long Build"}'
BREADCRUMB = '"@type": "BreadcrumbList",'
MEDIA_OPEN = '"associatedMedia": {'
MEDIA_CLOSE = 'arena."\n  }'
NEXT_DATA = ('<script id="__NEXT_DATA__" type="application/json">'
             '{"props": {"episode": {"datePublished": "2025-09-17T23:05:00+02:00"}}}</script>\n</head>')
ENTITY = re.compile(r"&(#\d+|#x[0-9a-fA-F]+|[A-Za-z]+);")
SLUG = "idris-okonkwo"
CAND = {"url": "https://podcasts.happyscribe.com/the-long-build/idris-okonkwo-on-grid-batteries",
        "episode": "idris-okonkwo-on-grid-batteries", "show": "The Long Build"}
# The three keys that carry a statement date. They are written together or not
# at all.
DATE_KEYS = ("statement_date", "statement_date_basis", "hs_date_published")
# The fields this change adds to a record. YEAR strips them to prove the judge
# prompt never reads them.
NEW_FIELDS = DATE_KEYS + ("hs_date_unreadable", "hs_dates_elsewhere", "text_unescaped")

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


class FakeResponse:
    def __init__(self, text: str):
        self.text = text
        self.status_code = 200


class FakeSession:
    """Serves pages and records every URL asked for, so a test can prove that a
    cached fetch never reached the network. A single page is served for every
    URL; a dict serves by URL and raises KeyError for any other."""

    def __init__(self, pages):
        self.pages = pages
        self.urls: list[str] = []

    def get(self, url, timeout=60, allow_redirects=True):
        self.urls.append(url)
        return FakeResponse(self.pages if isinstance(self.pages, str) else self.pages[url])


@contextlib.contextmanager
def pinned_clock(stamp: str | None):
    """Pin the one clock fetch_one reads, F.utcnow, to a fixed UTC stamp."""
    if stamp is None:
        yield
        return
    real = F.utcnow
    F.utcnow = lambda: stamp
    try:
        yield
    finally:
        F.utcnow = real


def fetch(page: str, out_dir: Path, force: bool = False,
          fetched_at: str | None = None) -> tuple[dict, dict | None, FakeSession]:
    """Run the real fetch_one against a served page. Returns the status, the
    record written (or None), and the session."""
    session = FakeSession(page)
    with pinned_clock(fetched_at):
        status = F.fetch_one(CAND, SLUG, out_dir, session, F.Pacer(0.0), force)
    path = status.get("path")
    rec = json.loads(Path(path).read_text()) if path else None
    return status, rec, session


def twin(old: str, new: str, page: str = PAGE) -> str:
    """`page` with one exact substitution, refusing a substitution that matches
    nothing: a twin identical to its source proves nothing."""
    if page.count(old) != 1:
        raise SystemExit(f"fixture drifted: {old!r} occurs {page.count(old)} times, want 1")
    return page.replace(old, new)


UNDATED = twin(DATE_LINE, "")


def date_view(s: dict, r: dict | None) -> str:
    """The status and the date fields of a record, for a failure message."""
    keys = DATE_KEYS + ("hs_date_unreadable", "hs_dates_elsewhere")
    return f"status={json.dumps(s)} record={r and {k: r[k] for k in keys if k in r}}"


def undated_but_kept(s: dict, r: dict | None, base_text: str, reason_has: str) -> tuple[bool, str]:
    """The transcript was written in full, with no statement date, and both the
    record and fetch_one's status say why, in words that name the cause."""
    if s.get("status") != "ok" or r is None:
        return False, date_view(s, r)
    why = r.get("hs_date_unreadable")
    ok = (not any(k in r for k in DATE_KEYS)
          and isinstance(why, str) and reason_has in why
          and s.get("hs_date_unreadable") == why
          and r["text"] == base_text)
    return ok, f"want the reason to contain {reason_has!r}; " + date_view(s, r)


def dated(s: dict, r: dict | None, want: str) -> tuple[bool, str]:
    """Fetched with statement_date `want`, the page's own raw value, and no
    unreadable reason."""
    ok = (s.get("status") == "ok" and r is not None
          and r.get("statement_date") == want
          and r.get("statement_date_basis") == "publication_date"
          and "hs_date_unreadable" not in r and "hs_date_unreadable" not in s)
    return ok, date_view(s, r)


def run_main(argv: list[str], pages: dict) -> tuple[int, str, str]:
    """Run the real main() with a fake session. Returns (rc, stdout, stderr)."""
    real_argv, real_session = sys.argv, F.make_session
    sys.argv = ["fetch_happyscribe.py", *argv]
    F.make_session = lambda: FakeSession(pages)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = F.main()
    finally:
        sys.argv, F.make_session = real_argv, real_session
    return rc, out.getvalue(), err.getvalue()


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_mod", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    # A zone whose date differs from UTC for nine hours of every day. Under it,
    # a fetcher that reads a local date instead of the UTC date gets the wrong
    # day for most of the UTC cases below, whatever zone the machine is in. On a
    # UTC machine the same regression would pass.
    os.environ["TZ"] = "Asia/Tokyo"
    time.tzset()

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        print("TEXT: the JSON path decodes HTML entities, as the fallback already did")
        status, rec, _ = fetch(PAGE, td / "base")
        check("the fixture fetches", status["status"] == "ok", json.dumps(status))
        if rec is None:
            print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
            return 1
        text = rec["text"]
        left = sorted(set(m.group(0) for m in ENTITY.finditer(text)))
        check("no HTML entity survives in the stored text", not left, f"still escaped: {left}")
        for want in ("we're going to build something bigger", "R&D because chemistry",
                     '"patient capital"', "margins < 10 percent"):
            check(f"text reads {want!r}", want in text)
        check("timestamps survive, so the JSON path was read and not the HTML fallback",
              rec["n_timestamp_marks"] == 27 and "\n[00:00:14] " in text,
              f"n_timestamp_marks={rec['n_timestamp_marks']}")
        check("title is decoded", rec["hs_title"].startswith(
            "Idris Okonkwo on grid batteries, patient capital & why we're early"), rec["hs_title"])

        print("DATE: statement_date comes from JSON-LD datePublished, in UTC")
        check("statement_date is the UTC date of datePublished",
              rec.get("statement_date") == "2025-09-17", repr(rec.get("statement_date")))
        check("statement_date_basis is publication_date",
              rec.get("statement_date_basis") == "publication_date", repr(rec.get("statement_date_basis")))
        check("the raw value is kept beside it as evidence",
              rec.get("hs_date_published") == "2025-09-17T23:05:00+02:00", repr(rec.get("hs_date_published")))
        check("a readable date carries no unreadable reason and no other dates",
              "hs_date_unreadable" not in rec and "hs_date_unreadable" not in status
              and "hs_dates_elsewhere" not in rec, date_view(status, rec))
        try:
            own = L.own_statement_date(rec)
        except L.PredictionError as exc:
            own = ("raised", str(exc))
        check("predictions_lib reads the pair as a declared publication date",
              own == ("2025-09-17", "publication_date"), repr(own))
        check("the date is not the fetch date",
              rec.get("statement_date") != rec["fetched_at_utc"][:10], rec["fetched_at_utc"])

        print("UTC: the UTC date, in both directions, run in Asia/Tokyo")
        check("this process really is in Asia/Tokyo", time.strftime("%z") == "+0900", time.strftime("%z"))
        cases = [
            ("+02:00 at 01:30 on the 18th is the 17th in UTC", "2025-09-18T01:30:00+02:00", "2025-09-17"),
            ("-07:00 at 20:30 on the 17th is the 18th in UTC", "2025-09-17T20:30:00-07:00", "2025-09-18"),
            ("Z is taken as UTC", "2025-09-17T21:05:00Z", "2025-09-17"),
            ("Z at 20:30 on the 17th is the 17th, though Tokyo is already on the 18th",
             "2025-09-17T20:30:00Z", "2025-09-17"),
        ]
        for i, (name, value, want) in enumerate(cases):
            s, r, _ = fetch(twin(DATE_LINE, f'"datePublished": "{value}",'), td / f"utc{i}")
            check(name, *dated(s, r, want))

        print("OWNER: only the object that carries the transcript dates it")
        s, r, _ = fetch(twin(EPISODE_NAME, EPISODE_NAME + ' "datePublished": "2025-06-02T10:00:00Z",'),
                        td / "own_dated")
        ok, d = dated(s, r, "2025-09-17")
        check("a dated BlogPosting with a nested episode on another date gives the BlogPosting's date",
              ok and r.get("hs_date_published") == "2025-09-17T23:05:00+02:00", d)
        check("the nested date is kept as evidence, with where it was found",
              r is not None and r.get("hs_dates_elsewhere")
              == [{"path": "ld[0].isPartOf.datePublished", "value": "2025-06-02T10:00:00Z"}],
              repr(r and r.get("hs_dates_elsewhere")))
        undated_owner = [
            ("an undated BlogPosting with a dated isPartOf",
             twin(EPISODE_NAME, EPISODE_NAME + ' "datePublished": "2019-03-01T00:00:00Z",', UNDATED),
             "ld[0].isPartOf.datePublished", "2019-03-01T00:00:00Z"),
            ("an undated BlogPosting with a dated partOfSeries",
             twin(SERIES, SERIES[:-1] + ', "datePublished": "2019-03-01T00:00:00Z"}', UNDATED),
             "ld[0].isPartOf.partOfSeries.datePublished", "2019-03-01T00:00:00Z"),
            ("an undated BlogPosting beside a dated JSON-LD block about something else",
             twin(BREADCRUMB, BREADCRUMB + ' "datePublished": "2024-01-05T00:00:00Z",', UNDATED),
             "ld[1].datePublished", "2024-01-05T00:00:00Z"),
        ]
        for i, (name, page, path, value) in enumerate(undated_owner):
            s, r, _ = fetch(page, td / f"owner{i}")
            check(f"{name}: fetched with no statement date",
                  s["status"] == "ok" and r is not None and not any(k in r for k in DATE_KEYS),
                  date_view(s, r))
            check(f"{name}: not reported unreadable, because the transcript's own object states no date",
                  r is not None and "hs_date_unreadable" not in r and "hs_date_unreadable" not in s,
                  date_view(s, r))
            check(f"{name}: the other date is evidence only",
                  r is not None and r.get("hs_dates_elsewhere") == [{"path": path, "value": value}],
                  repr(r and r.get("hs_dates_elsewhere")))
            if r is not None:
                check(f"{name}: predictions_lib reads it as unknown",
                      L.own_statement_date(r) == (None, "unknown"))
        s, r, _ = fetch(twin(MEDIA_CLOSE, 'arena."\n  }]', twin(MEDIA_OPEN, '"associatedMedia": [{')),
                        td / "media_list")
        check("associatedMedia written as a list still names the object that owns the transcript",
              *dated(s, r, "2025-09-17"))
        s, r, _ = fetch(twin(BREADCRUMB, BREADCRUMB + ' "associatedMedia": '
                             '{"@type": "AudioObject", "transcript": "another episode"},'), td / "two_owners")
        check("two JSON-LD objects that carry a transcript: kept, undated, with the reason",
              *undated_but_kept(s, r, text, "2 JSON-LD objects carry a transcript"))
        s, r, _ = fetch(twin(MEDIA_OPEN, '"audio": {'), td / "no_owner")
        check("no JSON-LD object carries the transcript while the page names datePublished: "
              "kept, undated, with the reason", *undated_but_kept(s, r, text, "0 JSON-LD objects carry a transcript"))

        print("NODATE: no datePublished, no key, and nothing stands in for it")
        s, r, _ = fetch(UNDATED, td / "nodate")
        check("a page without datePublished still fetches", s["status"] == "ok", json.dumps(s))
        if r is not None:
            check("no statement_date key", "statement_date" not in r, repr(r.get("statement_date")))
            check("no statement_date_basis key", "statement_date_basis" not in r)
            check("no hs_date_published key", "hs_date_published" not in r)
            check("no hs_date_unreadable key, because the page states no date",
                  "hs_date_unreadable" not in r and "hs_date_unreadable" not in s, date_view(s, r))
            check("dateCreated and dateModified are not used as a fallback",
                  "2025-09-17" not in json.dumps({k: v for k, v in r.items() if k != "text"}))
            check("predictions_lib reads it as unknown", L.own_statement_date(r) == (None, "unknown"))

        print("NULL: a JSON null datePublished states no date")
        s, r, _ = fetch(twin(DATE_LINE, '"datePublished": null,'), td / "null")
        check("fetched, with no date key and no unreadable reason",
              s["status"] == "ok" and r is not None and not any(k in r for k in DATE_KEYS)
              and "hs_date_unreadable" not in r and "hs_dates_elsewhere" not in r, date_view(s, r))

        print("OUTSIDE: a datePublished the fetcher does not read is not silently dropped")
        s, r, _ = fetch(twin("</head>", NEXT_DATA, UNDATED), td / "outside")
        check("named only outside JSON-LD: kept, undated, with the reason",
              *undated_but_kept(s, r, text, "outside any JSON-LD block"))
        s, r, _ = fetch(twin("</head>", NEXT_DATA), td / "outside_dated")
        check("the same outside mention beside a dated BlogPosting leaves the BlogPosting's date",
              *dated(s, r, "2025-09-17"))

        print("UNREADABLE: the transcript is kept, the date is not, and the record says why")
        unreadable = [
            ("not ISO 8601", twin(DATE_LINE, '"datePublished": "September 17, 2025",'),
             "not an ISO 8601 timestamp"),
            ("no UTC offset", twin(DATE_LINE, '"datePublished": "2025-09-17T23:05:00",'), "no UTC offset"),
            ("a bare date carries no offset", twin(DATE_LINE, '"datePublished": "2025-09-17",'),
             "no UTC offset"),
            ("not a string", twin(DATE_LINE, '"datePublished": 20250917,'), "not a string"),
            ("an empty string", twin(DATE_LINE, '"datePublished": "",'), "not an ISO 8601 timestamp"),
            ("a list of values", twin(DATE_LINE, '"datePublished": ["2025-09-17T23:05:00+02:00"],'),
             "not a string"),
            ("a JSON-LD block that names datePublished but does not parse",
             twin('"inLanguage": "en",', '"inLanguage": "en"'), "not valid JSON"),
            ("a date after the fetch", twin(DATE_LINE, '"datePublished": "2099-01-01T00:00:00Z",'),
             "the UTC date this record was fetched"),
        ]
        kept = None  # the first record that passed as unreadable, for YEAR below
        for i, (name, page, reason) in enumerate(unreadable):
            s, r, _ = fetch(page, td / f"unreadable{i}")
            ok, d = undated_but_kept(s, r, text, reason)
            check(f"{name}: kept, undated, with the reason", ok, d)
            if ok and kept is None:
                kept = r
        check("predictions_lib reads an unreadable date as unknown",
              kept is not None and L.own_statement_date(kept) == (None, "unknown"), repr(kept and kept.keys()))
        s, r, _ = fetch(twin('"@type": "BreadcrumbList",', '"@type": "BreadcrumbList"'), td / "otherblock")
        check("a broken JSON-LD block that names no datePublished is not a date failure",
              *dated(s, r, "2025-09-17"))

        print("FUTURE: the bound is the UTC date of the record's own fetched_at_utc")
        fetched = "2025-09-17T23:59:59Z"
        s, r, _ = fetch(PAGE, td / "future0", fetched_at=fetched)
        check("the record's fetched_at_utc is the stamp the bound was read from",
              r is not None and r["fetched_at_utc"] == fetched, repr(r and r["fetched_at_utc"]))
        check("a date on the fetch's own UTC date is accepted", *dated(s, r, "2025-09-17"))
        s, r, _ = fetch(twin(DATE_LINE, '"datePublished": "2025-09-18T00:30:00Z",'), td / "future1",
                        fetched_at=fetched)
        check("the next UTC date is unreadable", *undated_but_kept(s, r, text, "2025-09-18"))
        s, r, _ = fetch(twin(DATE_LINE, '"datePublished": "2025-09-18T01:30:00+02:00",'), td / "future2",
                        fetched_at=fetched)
        check("the 18th at +02:00 is the 17th in UTC, so it is not after the fetch",
              *dated(s, r, "2025-09-17"))
        s, r, _ = fetch(PAGE, td / "future3", fetched_at="2025-09-17T00:00:00Z")
        check("the bound is a date, not an instant: published 21:05Z, fetched 00:00Z the same day",
              *dated(s, r, "2025-09-17"))

        print("SUMMARY: the real main() counts and names records written without a date")
        second = {"url": CAND["url"] + "-2", "episode": CAND["episode"] + "-2", "show": CAND["show"]}
        cands = td / "summary" / "candidates.json"
        cands.parent.mkdir(parents=True)
        cands.write_text(json.dumps({SLUG: [CAND, second]}))
        rc, out, err = run_main(
            ["--fetch", "--study", "leaders", "--candidates", str(cands),
             "--out", str(td / "summary" / "out"), "--errors", str(td / "summary" / "errors.jsonl"),
             "--interval", "0", "--workers", "1"],
            {CAND["url"]: PAGE, second["url"]: twin(DATE_LINE, '"datePublished": "2025-09-17T23:05:00",')})
        try:
            summary = json.loads(out)
        except ValueError:
            summary = {}
        check("main exits 0 and prints a JSON summary", rc == 0 and bool(summary), f"rc={rc} out={out!r}")
        check("both transcripts count as fetched, and neither as failed",
              summary.get("attempted") == 2 and summary.get("newly_fetched") == 2
              and summary.get("failed") == 0, json.dumps(summary))
        check("the one written without a date is counted",
              summary.get("written_with_unreadable_date") == 1, json.dumps(summary))
        listed = summary.get("unreadable_dates") or []
        check("and named, with its reason",
              len(listed) == 1 and listed[0].get("leader_slug") == SLUG
              and listed[0].get("source_id") == "hs-idris-okonkwo-on-grid-batteries-2"
              and "no UTC offset" in (listed[0].get("hs_date_unreadable") or ""), json.dumps(listed))
        check("and logged as it happens", "hs-idris-okonkwo-on-grid-batteries-2" in err
              and "no UTC offset" in err, err[-400:])

        print("YEAR: declared_year stays 0 and the leaders judge prompt does not move")
        check("declared_year is still 0", rec.get("declared_year") == 0, repr(rec.get("declared_year")))
        g = load("grade")
        gc = load("grading_contract")
        fields = json.loads((REPO / "profiles" / "pundits.json").read_text())["identity_treatment"]["metadata_fields"]
        _, evidence_rec, _ = fetch(twin(EPISODE_NAME, EPISODE_NAME + ' "datePublished": "2019-03-01T00:00:00Z",',
                                        UNDATED), td / "year_evidence")
        for label, r in (("a dated record", rec), ("an unreadable-date record", kept),
                         ("a record with dates elsewhere", evidence_rec)):
            if r is None:
                check(f"{label}: exists for the prompt check", False)
                continue
            stripped = {k: v for k, v in r.items() if k not in NEW_FIELDS}
            for mode in ("blinded", "open"):
                p_new = g.build_judge_prompt(r, mode, "RUBRIC", "SCHEMA")
                p_old = g.build_judge_prompt(stripped, mode, "RUBRIC", "SCHEMA")
                check(f"{label}, {mode}: grade.py prompt is byte-identical without the new fields",
                      p_new == p_old)
                check(f"{label}, {mode}: the judge still reads 'Approximate year: unknown'",
                      "Approximate year: unknown" in p_new)
            check(f"{label}: grading_contract metadata is identical without the new fields",
                  gc.metadata_block(r, fields) == gc.metadata_block(stripped, fields))

        print("CACHED: an already-fetched transcript is never rewritten")
        old = td / "cached" / SLUG / f"hs-{CAND['episode']}.json"
        old.parent.mkdir(parents=True)
        old.write_text(json.dumps({"source_id": old.stem, "declared_year": 0,
                                   "text": "[00:00:01] we&#39;re still escaped"}, indent=1))
        before = old.read_bytes()
        s, _, session = fetch(PAGE, td / "cached")
        check("fetch_one reports it cached", s["status"] == "cached", json.dumps(s))
        check("the page was never requested", session.urls == [], repr(session.urls))
        check("the file's bytes are unchanged", old.read_bytes() == before)

        print("MARKER: a new record says its text is already unescaped")
        check("text_unescaped is True", rec.get("text_unescaped") is True, repr(rec.get("text_unescaped")))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
