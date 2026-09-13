#!/usr/bin/env python3
"""Guards on the pure prediction library, each written failing first.

Every rule here exists because the 2026-09-09 probe showed where a looser
version goes wrong: a fuzzy quote match that "grounds" a paraphrase, an id that
moves when a transcript is re-repaired, a hedged confidence that becomes a
number, a write that lands in a directory this clone does not own.

  GROUND    normalise strips only timestamp marks; exact grounding maps to original offsets
  ID        the id ignores case, punctuation, marks and whitespace, and nothing else
  DEDUPE    near-identical spans collapse to the longer one; merely overlapping spans are two records
  DATE      statement date comes from yt_upload_date, never declared_year; malformed fails loud
  CUTOFF    date-only publication gives a 00:00 UTC cutoff at date precision; unknown gives none
  GUARD     writes under data/ are allowed ONLY under data/predictions
  EXCLUDE   the exclusion list parses and covers every retire entry of its source manifests
  WALKER    the schema-subset walker enforces each keyword and rejects unknown ones
  DERIVED   qualifies / accepted / provenance are computed the same way everywhere

  .venv/bin/python scripts/test_predictions_lib.py
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if detail and not ok:
        print(f"          {detail}")


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_mod", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TEXT = ("[00:00:01] so the question is where does this go [00:01:00] I think by 2030 most code will be "
        "written by AI, honestly. [Music] and that’s the thing people don't get. [00:02:00] I think by 2030 "
        "most code will be written by AI, honestly. that is my bet")


def test_ground(L) -> None:
    n = L.normalise("Hello, [00:01:02] World’s [Music] test!")
    check("GROUND: marks stripped, [Music] kept, case and punctuation folded",
          n == "hello world s music test", n)
    norm, omap = L.normalise_with_map(TEXT)
    check("GROUND: offset map points at the original characters",
          all(TEXT[omap[i]].lower() == norm[i] for i in range(len(norm)) if norm[i] != " "))
    loc = L.locate_quote(TEXT, "and that's the thing people don't get")
    check("GROUND: curly vs straight apostrophe still grounds exactly",
          "start" in loc and TEXT[loc["start"]:loc["end"]] == "and that’s the thing people don't get", str(loc))
    loc = L.locate_quote(TEXT, "where does this go I think by 2030")
    check("GROUND: a quote spanning a timestamp mark grounds and the span includes the mark",
          "start" in loc and "[00:01:00]" in TEXT[loc["start"]:loc["end"]], str(loc))
    check("GROUND: absent quote is not_found",
          L.locate_quote(TEXT, "we will ship a rocket")["error"] == "not_found")
    amb = L.locate_quote(TEXT, "by 2030 most code will be written by AI")
    check("GROUND: a repeated quote without a hint is ambiguous_no_hint with the count",
          amb.get("error") == "ambiguous_no_hint" and amb["occurrences"] == 2, str(amb))
    hinted = L.locate_quote(TEXT, "by 2030 most code will be written by AI", "[00:02:00]")
    check("GROUND: the timestamp hint picks the occurrence under that mark",
          "start" in hinted and hinted["start"] > TEXT.index("[00:02:00]") and hinted["occurrences"] == 2, str(hinted))
    check("GROUND: a partial-word match is not a match",
          L.locate_quote("the cat sat", "he cat")["error"] == "not_found")
    check("GROUND: nearest_mark before an offset, and unmarked when none precedes",
          L.nearest_mark(TEXT, TEXT.index("honestly")) == "[00:01:00]" and L.nearest_mark("no marks here", 3) == "unmarked")
    check("GROUND: mark_seconds", L.mark_seconds("[01:02:03]") == 3723 and L.mark_seconds("unmarked") is None)
    before, after = L.context_window(TEXT, TEXT.index("I think by 2030"), TEXT.index("honestly"), words=3)
    check("GROUND: context window is N whole tokens each side",
          before == "this go [00:01:00]" and after == "honestly. [Music] and", f"{before!r} / {after!r}")
    b2, a2 = L.context_window("a b c", 2, 3, words=400)
    check("GROUND: context window clips at the ends", b2 == "a" and a2 == "c", f"{b2!r} / {a2!r}")
    check("GROUND: word count ignores marks", L.quote_word_count("one [00:00:01] two three") == 3)
    src = inspect.getsource(L)
    check("GROUND: no n-gram or fuzzy fallback in the library",
          "gram" not in src.lower() and "fuzzy" not in src.lower().replace("no fuzzy", ""))


def test_id(L) -> None:
    a = L.prediction_id("x/y", "By 2030, most code will be written by AI!")
    b = L.prediction_id("x/y", "by 2030 most [00:01:00] code   will be written by ai")
    check("ID: case, punctuation, marks and whitespace do not change the id", a == b and len(a) == 16)
    check("ID: transcript changes the id", L.prediction_id("x/z", "by 2030 most code will be written by ai") != a)
    check("ID: text changes the id", L.prediction_id("x/y", "by 2031 most code will be written by ai") != a)


def test_dedupe(L) -> None:
    c = lambda s, e, i: {"start": s, "end": e, "prediction_id": i}  # noqa: E731
    kept, dropped = L.dedupe_overlapping([c(0, 100, "a"), c(2, 100, "b"), c(200, 300, "c")])
    check("DEDUPE: near-identical spans collapse to the longer, and the drop names its keeper",
          [k["prediction_id"] for k in kept] == ["a", "c"] and dropped == [{"prediction_id": "b", "start": 2, "end": 100, "kept_by": "a"}],
          f"{kept} {dropped}")
    kept, _ = L.dedupe_overlapping([c(2, 100, "b"), c(0, 100, "a")])
    check("DEDUPE: order of input does not matter", [k["prediction_id"] for k in kept] == ["a"])
    kept, dropped = L.dedupe_overlapping([c(0, 100, "a"), c(0, 200, "b")])
    check("DEDUPE: a span that holds another plus as much text again is a SECOND record (the Hotz case)",
          [k["prediction_id"] for k in kept] == ["a", "b"] and dropped == [], f"{kept} {dropped}")
    kept, _ = L.dedupe_overlapping([c(0, 10, "b"), c(0, 10, "a")])
    check("DEDUPE: identical spans tie on the smaller id", [k["prediction_id"] for k in kept] == ["a"])
    kept, dropped = L.dedupe_overlapping([c(0, 100, "a"), c(10, 110, "b"), c(20, 120, "c")])
    check("DEDUPE: a chain of near-identical spans resolves against KEPT spans (b and c both fold into a)",
          [k["prediction_id"] for k in kept] == ["a"] and {d["kept_by"] for d in dropped} == {"a"}, str(kept))
    again, d2 = L.dedupe_overlapping(kept)
    check("DEDUPE: idempotent", again == kept and d2 == [])
    check("DEDUPE: partly overlapping spans both survive",
          len(L.dedupe_overlapping([c(0, 100, "a"), c(50, 150, "b")])[0]) == 2)
    check("DEDUPE: span_overlap is shared chars over the longer span",
          L.span_overlap(c(0, 100, "a"), c(50, 150, "b")) == 0.5 and L.span_overlap(c(0, 100, "a"), c(200, 300, "b")) == 0
          and L.span_overlap(c(0, 100, "a"), c(0, 100, "b")) == 1.0)


def test_date(L) -> None:
    check("DATE: yt_upload_date YYYYMMDD -> ISO with basis",
          L.derive_statement_date({"yt_upload_date": "20250301"}) == ("2025-03-01", "youtube_upload_date"))
    check("DATE: missing upload date -> null, unknown; declared_year ignored",
          L.derive_statement_date({"declared_year": 2024}) == (None, "unknown"))
    for bad in ("2025-03-01", "20251301", 20250301):
        try:
            L.derive_statement_date({"yt_upload_date": bad, "source_id": "s"})
            check(f"DATE: malformed {bad!r} fails loud", False, "no exception")
        except L.PredictionError as exc:
            check(f"DATE: malformed {bad!r} fails loud", "statement_date" in str(exc))
    check("DATE: declared_year never appears in the library",
          "declared_year" not in inspect.getsource(L).replace("declared_year is never consulted", "").replace("never declared_year", "").replace("declared_year (a hardcoded constant)", "").replace("declared_year is a hardcoded constant", ""))
    check("DATE: target_date formats", all(L.target_date_valid(s) for s in (None, "2030", "2030-06", "2030-06-15"))
          and not any(L.target_date_valid(s) for s in ("2030-13", "June 2030", "2030-06-31", "30")))


def test_cutoff(L) -> None:
    c = L.publication_cutoff({"yt_upload_date": "20250301"})
    check("CUTOFF: date-only -> 00:00:00Z at the date, precision date, basis publication_date_only",
          c == {"basis": "publication_date_only", "requested_cutoff_utc": "2025-03-01T00:00:00Z",
                "precision": "date", "rule": L.DATE_ONLY_RULE}, str(c))
    c2 = L.publication_cutoff({"source": {"statement_date": "2025-03-01", "statement_date_basis": "youtube_upload_date"}})
    check("CUTOFF: works from a prediction record too", c2["requested_cutoff_utc"] == "2025-03-01T00:00:00Z")
    c3 = L.publication_cutoff({"source": {"statement_date": None, "statement_date_basis": "unknown"}})
    check("CUTOFF: unknown date -> no cutoff, precision none",
          c3["basis"] == "unknown" and c3["requested_cutoff_utc"] is None and c3["precision"] == "none")


def test_guard(L) -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "data"
        (root / "predictions").mkdir(parents=True)
        (root / "grades").mkdir()
        ok = lambda p: L.guard_data_path(p, root)  # noqa: E731
        check("GUARD: data/predictions/x.jsonl allowed", ok(root / "predictions" / "a" / "x.jsonl").name == "x.jsonl")
        check("GUARD: data/predictions itself allowed", ok(root / "predictions") == (root / "predictions").resolve())
        for bad in (root / "grades" / "g.json", root / "transcripts_open" / "t.json",
                    root / "predictions" / ".." / "grades" / "g.json", root, root / "results.json"):
            try:
                ok(bad)
                check(f"GUARD: refuses {bad.relative_to(root.parent)}", False, "allowed")
            except L.RefusedDataWrite as exc:
                check(f"GUARD: refuses {bad.relative_to(root.parent)}", "refusing to write" in str(exc))
        check("GUARD: a path outside data/ passes", ok(Path(td) / "elsewhere" / "f.txt").name == "f.txt")
        L.write_prediction_file(root / "predictions" / "p" / "f.jsonl", "{}\n", root)
        check("GUARD: write_prediction_file lands atomically under the allowed tree",
              (root / "predictions" / "p" / "f.jsonl").read_text() == "{}\n" and not list((root / "predictions" / "p").glob("*.tmp")))
        try:
            L.write_prediction_file(root / "grades" / "f.json", "{}", root)
            check("GUARD: write_prediction_file refuses data/grades", False)
        except L.RefusedDataWrite:
            check("GUARD: write_prediction_file refuses data/grades", not (root / "grades" / "f.json").exists())
    check("GUARD: the real data root resolves through the symlink",
          L.data_root() == (REPO / "data").resolve() and not L.data_root().is_symlink())


def test_exclude(L) -> None:
    path = REPO / "scripts" / "predictions_exclusions.json"
    ex = L.load_exclusions(path)
    check("EXCLUDE: file parses with schema_version 1 and non-empty", len(ex) > 0)
    d = json.loads(path.read_text())
    missing = []
    for src in d["sources"]:
        for e in json.loads((REPO / src).read_text()):
            if e["action"] == "retire" and f'{e["leader_slug"]}/{e["source_id"]}' not in ex:
                missing.append(f'{e["leader_slug"]}/{e["source_id"]}')
    check("EXCLUDE: every retire entry of every listed source manifest is excluded", not missing, str(missing))
    known = ["cc-wei/han-wei-shen-ughuv0", "michael-dell/project-nanda-wj3xga", "jeff-bezos/hal-sparks-olznjg",
             "arvind-krishna/preetika-rao-and-s-aishw-n-i6g5", "tim-sweeney/kaput-magazin-f-r-insolv-nddwao"]
    check("EXCLUDE: the integrity doc's wrong-person cases are all listed", all(k in ex for k in known))
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.json"
        p.write_text(json.dumps({"schema_version": 1, "exclusions": [{"transcript_id": "a/b", "reason": "r"}]}))
        try:
            L.load_exclusions(p)
            check("EXCLUDE: an entry without evidence fails loud", False)
        except L.PredictionError as exc:
            check("EXCLUDE: an entry without evidence fails loud", "evidence" in str(exc))


def test_walker(L) -> None:
    S = {"type": "object", "additionalProperties": False, "required": ["a", "b"],
         "properties": {"a": {"type": "integer", "minimum": 1, "maximum": 5},
                        "b": {"enum": ["x", "y", None]},
                        "c": {"type": ["string", "null"], "minLength": 2},
                        "d": {"const": 1},
                        "e": {"type": "array", "items": {"$ref": "#/$defs/g"}},
                        "f": {"anyOf": [{"type": "null"}, {"$ref": "#/$defs/g"}]}},
         "$defs": {"g": {"type": "object", "required": ["z"], "properties": {"z": {"type": "boolean"}}, "additionalProperties": False}}}
    check("WALKER: a valid object passes", L.check_schema({"a": 3, "b": "x", "c": None, "d": 1, "e": [{"z": True}], "f": None}, S) == [])
    cases = {
        "missing required": ({"a": 3}, "missing required b"),
        "unexpected property": ({"a": 3, "b": "x", "q": 1}, "unexpected property q"),
        "minimum": ({"a": 0, "b": "x"}, "< minimum"),
        "maximum": ({"a": 9, "b": "x"}, "> maximum"),
        "enum": ({"a": 3, "b": "w"}, "not in enum"),
        "type list": ({"a": 3, "b": "x", "c": 5}, "expected type"),
        "minLength": ({"a": 3, "b": "x", "c": "k"}, "< minLength"),
        "const": ({"a": 3, "b": "x", "d": 2}, "expected const"),
        "bool is not integer": ({"a": True, "b": "x"}, "expected type"),
        "items via $ref": ({"a": 3, "b": "x", "e": [{"z": "no"}]}, "$.e[0].z"),
        "anyOf": ({"a": 3, "b": "x", "f": {"z": 1}}, "matches no anyOf branch"),
    }
    for name, (obj, needle) in cases.items():
        errs = L.check_schema(obj, S)
        check(f"WALKER: {name}", any(needle in e for e in errs), str(errs))
    errs = L.check_schema({"a": 1}, {"type": "object", "pattern": "x"})
    check("WALKER: an unsupported keyword is an error, not ignored", errs and "unsupported keywords" in errs[0], str(errs))
    rs = L.load_record_schema()
    check("WALKER: the shipped record schema uses only supported keywords",
          not any("unsupported" in e for e in L.check_schema({}, rs)), str(L.check_schema({}, rs))[:200])


def test_derived(L) -> None:
    g = {k: True for k in L.GATES}
    check("DERIVED: extraction qualifies needs every gate and a criterion",
          L.extraction_qualifies(g, "By 2030 X") and not L.extraction_qualifies({**g, "committed": False}, "x")
          and not L.extraction_qualifies(g, "  "))
    v = {"status": "ok", "gates": g, "attribution": "subject", "claim_faithful": True}
    check("DERIVED: verification qualifies needs gates, subject attribution and faithful claim",
          L.verification_qualifies(v) is True and L.verification_qualifies({**v, "attribution": "interviewer"}) is False
          and L.verification_qualifies({**v, "claim_faithful": False}) is False
          and L.verification_qualifies({"status": "not_run"}) is None)
    check("DERIVED: accepted is the AND of the two",
          L.compute_accepted({"extraction": {"qualifies": True}, "verification": {"qualifies": True}})
          and not L.compute_accepted({"extraction": {"qualifies": True}, "verification": {"qualifies": None}}))
    check("DERIVED: probability language must carry a number or odds",
          L.probability_language_ok("70% chance") and L.probability_language_ok("one in three")
          and not L.probability_language_ok("very likely") and not L.probability_language_ok(None))
    p = L.normalise_provenance("fable", {"requested_model": "claude-fable-5-1", "judge_model": "claude-fable-5-1[1m]"}, "default", "claude")
    check("DERIVED: fable provenance is verified from judge_model",
          p["served_model"] == "claude-fable-5-1[1m]" and p["served_model_verified"] is True and p["account"] == "default")
    p = L.normalise_provenance("astra", {"requested_model": "gpt-6-astra", "served_model": "gpt-6-astra"}, None, "codex")
    check("DERIVED: astra provenance is an unverified echo", p["served_model_verified"] is False and p["account"] == "codex")
    p = L.normalise_provenance("gemini", {"requested_model": "g", "served_model": "g", "served_model_verified": True, "profile_identity": "a@b"}, None, "antigravity_gemini")
    check("DERIVED: gemini provenance is verified with the profile identity", p["served_model_verified"] is True and p["account"] == "a@b")
    # make_record: an invented probability is dropped and the candidate disqualified.
    rec = {"leader_slug": "x", "source_id": "y", "text": TEXT, "yt_upload_date": "20250301", "url": "u", "video_id": "v",
           "yt_title": "T", "declared_venue": "V", "declared_kind": "podcast", "word_count": 40, "duration_sec": 120}
    cand = {"quote": "that is my bet", "gates": g, "gate_notes": "", "resolution_criteria": "By 2030, share of code by AI > 50%",
            "normalized_claim": "c", "category": "ai_capability", "prediction_type": "milestone", "target_date": "2030",
            "target_date_text": "by 2030", "horizon": "explicit", "horizon_years_inferred": None, "horizon_evidence": None,
            "specificity": "high", "subject_control": "external",
            "confidence": {"type": "explicit_probability", "probability": 0.8, "verbatim_confidence_language": "that is my bet"}}
    loc = L.locate_quote(TEXT, cand["quote"])
    r = L.make_record(rec, {"name": "X Y", "role": "CEO", "company": "Co"}, cand, loc,
                      L.normalise_provenance("astra", {"requested_model": "m", "served_model": "m"}, None, "codex"),
                      "abcdef012345", "run1", "2026-09-10T00:00:00Z", {})
    check("DERIVED: make_record drops an invented probability and disqualifies the candidate",
          r["confidence"]["probability"] is None and r["confidence"]["type"] == "qualitative"
          and r["extraction"]["qualifies"] is False and "confidence_invented" in r["extraction"]["gate_notes"], json.dumps(r["confidence"]))
    check("DERIVED: make_record output validates against the record schema",
          L.check_schema(r, L.load_record_schema()) == [], str(L.check_schema(r, L.load_record_schema()))[:300])
    check("DERIVED: make_record grounds quote_original and word count from the transcript",
          r["source"]["quote_original"] == "that is my bet" and r["source"]["quote_word_count"] == 4
          and r["source"]["timestamp_mark"] == "[00:02:00]" and r["source"]["statement_date"] == "2025-03-01")
    check("DERIVED: sentinels exact", r["resolution"] == {"status": "not_started"} and r["consensus"] == {"status": "not_searched"})
    line = L.serialise_line(r)
    check("DERIVED: serialisation is sort_keys and round-trips", json.loads(line) == r and line.startswith('{"accepted"'))


def main() -> int:
    L = load("predictions_lib")
    test_ground(L)
    test_id(L)
    test_dedupe(L)
    test_date(L)
    test_cutoff(L)
    test_guard(L)
    test_exclude(L)
    test_walker(L)
    test_derived(L)
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
