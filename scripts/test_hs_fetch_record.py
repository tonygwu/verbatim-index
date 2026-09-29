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

  TEXT     the JSON transcript path returns decoded text, and the timestamps
           prove it was the JSON path and not the HTML fallback
  DATE     statement_date is the UTC date of JSON-LD datePublished, with basis
           publication_date, and predictions_lib reads the pair as declared
  UTC      the UTC date, not the page's local date, in both directions
  NODATE   no datePublished gives no statement_date key and no basis key; the
           fetch time is never a stand-in
  LOUD     a datePublished the fetcher cannot read as one UTC date fails the
           fetch under its own taxonomy entry and writes nothing
  YEAR     declared_year stays 0, and the leaders judge prompt is byte-identical
           with and without the new fields
  CACHED   an already-fetched file is never rewritten
  MARKER   a new record says its text is already unescaped, so a later
           read-time view (design section 4.5) does not unescape it twice

The fixture is a synthetic page shaped like the archived one, under
scripts/fixtures/happyscribe/. No network, no quota, no data/.

  .venv/bin/python scripts/test_hs_fetch_record.py
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import fetch_happyscribe as F  # noqa: E402
import predictions_lib as L  # noqa: E402

FIXTURE = REPO / "scripts" / "fixtures" / "happyscribe" / "episode_page.html"
PAGE = FIXTURE.read_text(encoding="utf-8")
DATE_LINE = '"datePublished": "2025-09-17T23:05:00+02:00",'
ENTITY = re.compile(r"&(#\d+|#x[0-9a-fA-F]+|[A-Za-z]+);")
SLUG = "idris-okonkwo"
CAND = {"url": "https://podcasts.happyscribe.com/the-long-build/idris-okonkwo-on-grid-batteries",
        "episode": "idris-okonkwo-on-grid-batteries", "show": "The Long Build"}
# The fields this change adds to a record. YEAR strips them to prove the judge
# prompt never reads them.
NEW_FIELDS = ("statement_date", "statement_date_basis", "hs_date_published", "text_unescaped")

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


class FakeResponse:
    def __init__(self, text: str):
        self.text = text
        self.status_code = 200


class FakeSession:
    """Serves one page and records every URL asked for, so a test can prove
    that a cached fetch never reached the network."""

    def __init__(self, page: str):
        self.page = page
        self.urls: list[str] = []

    def get(self, url, timeout=60, allow_redirects=True):
        self.urls.append(url)
        return FakeResponse(self.page)


def fetch(page: str, out_dir: Path, force: bool = False) -> tuple[dict, dict | None, FakeSession]:
    """Run the real fetch_one against a served page. Returns the status, the
    record written (or None), and the session."""
    session = FakeSession(page)
    status = F.fetch_one(CAND, SLUG, out_dir, session, F.Pacer(0.0), force)
    path = status.get("path")
    rec = json.loads(Path(path).read_text()) if path else None
    return status, rec, session


def twin(old: str, new: str) -> str:
    """The fixture with one exact substitution, refusing a substitution that
    matches nothing: a twin identical to the fixture proves nothing."""
    if PAGE.count(old) != 1:
        raise SystemExit(f"fixture drifted: {old!r} occurs {PAGE.count(old)} times, want 1")
    return PAGE.replace(old, new)


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_mod", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
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
              rec.get("hs_date_published") == ["2025-09-17T23:05:00+02:00"], repr(rec.get("hs_date_published")))
        try:
            own = L.own_statement_date(rec)
        except L.PredictionError as exc:
            own = ("raised", str(exc))
        check("predictions_lib reads the pair as a declared publication date",
              own == ("2025-09-17", "publication_date"), repr(own))
        check("the date is not the fetch date",
              rec.get("statement_date") != rec["fetched_at_utc"][:10], rec["fetched_at_utc"])

        print("UTC: the UTC date, in both directions")
        cases = [
            ("+02:00 at 01:30 on the 18th is the 17th in UTC", "2025-09-18T01:30:00+02:00", "2025-09-17"),
            ("-07:00 at 20:30 on the 17th is the 18th in UTC", "2025-09-17T20:30:00-07:00", "2025-09-18"),
            ("Z is taken as UTC", "2025-09-17T21:05:00Z", "2025-09-17"),
        ]
        for i, (name, value, want) in enumerate(cases):
            s, r, _ = fetch(twin(DATE_LINE, f'"datePublished": "{value}",'), td / f"utc{i}")
            check(name, s["status"] == "ok" and r.get("statement_date") == want,
                  f"{s.get('status')} {s.get('detail', '')} {r and r.get('statement_date')!r}")
        s, r, _ = fetch(twin('"name": "Idris Okonkwo on grid batteries, patient capital &amp; why we&#39;re early",',
                             '"name": "Idris Okonkwo on grid batteries, patient capital &amp; why we&#39;re early",'
                             ' "datePublished": "2025-09-17T21:05:00Z",'), td / "agree")
        check("a second datePublished on the same UTC date is accepted",
              s["status"] == "ok" and r.get("statement_date") == "2025-09-17"
              and r.get("hs_date_published") == ["2025-09-17T21:05:00Z", "2025-09-17T23:05:00+02:00"],
              f"{s.get('status')} {s.get('detail', '')} {r and r.get('hs_date_published')!r}")

        print("NODATE: no datePublished, no key, and nothing stands in for it")
        s, r, _ = fetch(twin(DATE_LINE, ""), td / "nodate")
        check("a page without datePublished still fetches", s["status"] == "ok", json.dumps(s))
        if r is not None:
            check("no statement_date key", "statement_date" not in r, repr(r.get("statement_date")))
            check("no statement_date_basis key", "statement_date_basis" not in r)
            check("no hs_date_published key", "hs_date_published" not in r)
            check("dateCreated and dateModified are not used as a fallback",
                  "2025-09-17" not in json.dumps({k: v for k, v in r.items() if k != "text"}))
            check("predictions_lib reads it as unknown", L.own_statement_date(r) == (None, "unknown"))

        print("LOUD: a datePublished that cannot be read as one UTC date fails the fetch")
        loud = [
            ("not ISO 8601", twin(DATE_LINE, '"datePublished": "September 17, 2025",')),
            ("no UTC offset", twin(DATE_LINE, '"datePublished": "2025-09-17T23:05:00",')),
            ("a bare date carries no offset", twin(DATE_LINE, '"datePublished": "2025-09-17",')),
            ("not a string", twin(DATE_LINE, '"datePublished": 20250917,')),
            ("two different UTC dates", twin(
                '"name": "Idris Okonkwo on grid batteries, patient capital &amp; why we&#39;re early",',
                '"name": "Idris Okonkwo on grid batteries, patient capital &amp; why we&#39;re early",'
                ' "datePublished": "2025-06-02T10:00:00Z",')),
            ("a JSON-LD block that names datePublished but does not parse",
             twin('"inLanguage": "en",', '"inLanguage": "en"')),
        ]
        for i, (name, page) in enumerate(loud):
            s, r, _ = fetch(page, td / f"loud{i}")
            check(f"{name}: fails as unreadable_publication_date",
                  s["status"] == "failed" and s.get("error_type") == "unreadable_publication_date",
                  json.dumps(s))
            check(f"{name}: writes nothing", not (td / f"loud{i}" / SLUG).exists())
        s, r, _ = fetch(twin('"@type": "BreadcrumbList",', '"@type": "BreadcrumbList"'), td / "otherblock")
        check("a broken JSON-LD block that names no datePublished is not a date failure",
              s["status"] == "ok" and r.get("statement_date") == "2025-09-17", json.dumps(s))

        print("YEAR: declared_year stays 0 and the leaders judge prompt does not move")
        check("declared_year is still 0", rec.get("declared_year") == 0, repr(rec.get("declared_year")))
        g = load("grade")
        gc = load("grading_contract")
        stripped = {k: v for k, v in rec.items() if k not in NEW_FIELDS}
        for mode in ("blinded", "open"):
            p_new = g.build_judge_prompt(rec, mode, "RUBRIC", "SCHEMA")
            p_old = g.build_judge_prompt(stripped, mode, "RUBRIC", "SCHEMA")
            check(f"{mode}: grade.py prompt is byte-identical without the new fields", p_new == p_old)
            check(f"{mode}: the judge still reads 'Approximate year: unknown'",
                  "Approximate year: unknown" in p_new)
        fields = json.loads((REPO / "profiles" / "pundits.json").read_text())["identity_treatment"]["metadata_fields"]
        check("grading_contract metadata is identical without the new fields",
              gc.metadata_block(rec, fields) == gc.metadata_block(stripped, fields))

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
