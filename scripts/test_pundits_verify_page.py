#!/usr/bin/env python3
"""The speaker-check page's importer produces labels `report` accepts, and nothing it would not.

The page stores one db document per recording; `pundits_verify_page.py import`
turns an export of them into human_labels.json, which `pundits_pilot.py report`
reads to decide the P6 gate. A label the importer writes but `report` rejects
would silently drop a recording from the gate, and a partly answered recording
passed through would be a guessed label. So this checks the importer against
`report`'s own validator rather than restating its rules.

  VALID      every complete label passes pundits_pilot.human_errors unchanged
  EXCLUDED   a wrong-person or off-topic answer is kept, with all three fields
  PARTIAL    a recording missing any answer is left out and counted, never filled
  FOREIGN    a label for a recording not on the checklist stops the import
  PAGE       the built page carries each recording and no lean field
  TIMES      an excerpt's link time is the nearest earlier transcript mark
  LOCATE     a judge's quote is found in the raw transcript, [SUBJECT] and elisions included
  SIGNALS    a quote spanning a turn, a question in a conversation, and a self-naming
             quote are flagged; an ordinary answer is not
  HIDDEN     the judges' labels reach the private key file, never the page
  JOIN       quote answers join the key, and a foreign answer stops the import

  .venv/bin/python scripts/test_pundits_verify_page.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def main() -> int:
    print("pundits speaker-check page")
    import pundits_pilot as P
    import pundits_verify_page as V

    checklist = {"p/a": {}, "p/b": {}, "p/c": {}, "p/d": {}}
    docs = [
        {"key": "p/a", "subject_present": True, "venue": "conversation", "political_content": True, "checked_by": "operator"},
        {"key": "p/b", "subject_present": False, "venue": "solo", "political_content": True, "checked_by": "operator", "notes": "guest only"},
        {"key": "p/c", "subject_present": True, "venue": "reaction", "political_content": False, "checked_by": "operator"},
        {"key": "p/d", "subject_present": True, "political_content": True},
    ]
    res = V.to_labels(docs, checklist)

    print("\n[VALID]")
    errs = {k: P.human_errors(v) for k, v in res["labels"].items()}
    check("every imported label passes report's own validator", all(not e for e in errs.values()), str(errs))

    print("\n[EXCLUDED]")
    check("a wrong-person answer is imported", res["labels"].get("p/b", {}).get("subject_present") is False)
    check("an off-topic answer is imported", res["labels"].get("p/c", {}).get("political_content") is False)
    check("notes survive the import", res["labels"].get("p/b", {}).get("notes") == "guest only")

    print("\n[PARTIAL]")
    check("a recording with no format is left out", "p/d" not in res["labels"])
    check("and counted as partial rather than dropped silently", res["partial"] == ["p/d"], str(res["partial"]))

    print("\n[FOREIGN]")
    try:
        V.to_labels(docs + [{"key": "q/zz", "subject_present": True, "venue": "solo", "political_content": True}], checklist)
        check("a label for a recording not on the checklist stops the import", False, "it was accepted")
    except SystemExit as exc:
        check("a label for a recording not on the checklist stops the import", "not on the checklist" in str(exc), str(exc))

    print("\n[TIMES]")
    ex = V.excerpts("[00:00:00] " + " ".join(f"w{i}" for i in range(400)) + " [00:05:07] " + " ".join(f"x{i}" for i in range(600)))
    check("three excerpts are cut", len(ex) == 3, str(len(ex)))
    check("a late excerpt links to the nearest earlier mark", ex[-1]["t"] == 307, str([e["t"] for e in ex]))
    check("marks are stripped from the excerpt text", "[00:" not in "".join(e["text"] for e in ex))

    print("\n[LOCATE]")
    raw = "[00:00:10] hello there >> do you think this is right? >> I think it is right because the evidence says so"
    check("a quote spanning a turn is found", V.locate("do you think this is right? I think it is right", raw) is not None)
    check("a leading [SUBJECT] matches the replaced name",
          V.locate("[SUBJECT] said the evidence says so", "[00:00:01] Tim Walz said the evidence says so indeed") is not None)
    check("an elided quote matches on its longest piece",
          V.locate("a b ... the long part of the quote here", "x the long part of the quote here y") is not None)
    check("a quote not in the transcript is not located", V.locate("words that are not there at all", "nothing to see here") is None)
    check("a quote under four words is not located", V.locate("so it goes", "and so it goes on") is None)

    print("\n[SIGNALS]")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "t" / "p").mkdir(parents=True)
        (td / "g" / "fable" / "p").mkdir(parents=True)
        text = ("[00:00:00] welcome to the show >> so do you think taxes should go up for everyone? >> "
                "no I think the burden should fall on those who can carry it best and we should say so plainly "
                "[00:05:00] people ask me whether Jane Roe changed her mind and she did not at all ever "
                "and the long answer is that policy matters more than slogans in every single case here")
        (td / "t" / "p" / "s1.json").write_text(json.dumps({"video_id": "v1", "text": text, "yt_title": "T"}))
        ev = [
            {"quote": "so do you think taxes should go up for everyone?", "speaker": "subject"},
            {"quote": "no I think the burden should fall on those who can carry it best", "speaker": "subject"},
            {"quote": "people ask me whether Jane Roe changed her mind", "speaker": "subject"},
            {"quote": "policy matters more than slogans in every single case", "speaker": "subject"},
            {"quote": "welcome to the show and so on here", "speaker": "interlocutor"},
        ]
        (td / "g" / "fable" / "p" / "s1__fable__blinded__r0.json").write_text(json.dumps({
            "leader_slug": "p", "source_id": "s1", "judge": "fable", "mode": "blinded", "run": 0,
            "grade": {"venue_type": "conversation", "dimensions": {"d1": {"evidence": ev}}}}))
        roster = {"p": {"slug": "p", "name": "Jane Roe", "role": "host", "lean": "SECRET-LEAN"}}
        rows, key, rep = V.suspect_quotes(td / "g", td / "t", roster)
        sigs = {tuple(sorted(v["signals"])) for v in key.values()}
        texts = [c["text"] for r in rows for c in r["quotes"]]
        check("a question inside a conversation is flagged", any("question_in_conversation" in x for x in sigs), str(sigs))
        check("a quote naming the subject is flagged", any("names_subject" in x for x in sigs), str(sigs))
        check("an ordinary answer is not flagged", not any("policy matters" in t for t in texts), str(texts))
        check("a quote the judge gave to someone else is not in the queue", not any("welcome" in t for t in texts))
        check("the scan counts every subject quote it read", rep["subject_quotes"] == 4, str(rep))

        print("\n[HIDDEN]")
        page_json = json.dumps(rows)
        check("no judge name or label reaches the page rows",
              '"judge"' not in page_json and '"label"' not in page_json and "fable" not in page_json)
        check("the key holds the judge, mode and label for each flagged quote",
              all(j["judge"] == "fable" and j["label"] == "subject" for v in key.values() for j in v["judges"]))
        check("no lean value reaches the page rows", "SECRET-LEAN" not in page_json)

        print("\n[JOIN]")
        qid = next(iter(key))
        res = V.join_quotes([{"qid": qid, "answer": "other"}], key)
        check("an answer joins its key entry", res["answers"][qid]["answer"] == "other" and res["answers"][qid]["judges"])
        check("the tally counts it", res["tally"]["other"] == 1, str(res["tally"]))
        check("the report says its rates are among flagged quotes only", "FLAGGED" in res["note"])
        try:
            V.join_quotes([{"qid": "p:zz:1", "answer": "subject"}], key)
            check("an answer for a quote not in the key stops the import", False, "accepted")
        except SystemExit as exc:
            check("an answer for a quote not in the key stops the import", "not in the key" in str(exc), str(exc))

    print("\n[PAGE]")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "t" / "p").mkdir(parents=True)
        for sid in ("a", "b"):
            (td / "t" / "p" / f"{sid}.json").write_text(json.dumps({
                "video_id": f"vid{sid}", "text": "[00:00:00] Jane Roe said a thing " * 50,
                "yt_duration_sec": 1800, "word_count": 350, "yt_description": "with Jane Roe"}))
        (td / "c.json").write_text(json.dumps({"p/a": {"title": "A", "hints": []}, "p/b": {"title": "B", "hints": []}}))
        (td / "r.json").write_text(json.dumps({"roster": [{"slug": "p", "name": "Jane Roe", "role": "host", "lean": "SECRET-LEAN"}]}))
        V.build(SimpleNamespace(checklist=str(td / "c.json"), transcripts=str(td / "t"),
                                roster=str(td / "r.json"), out=str(td / "o.html"), grades=None, quote_key=None))
        page = (td / "o.html").read_text()
        check("the page carries every recording", '"key": "p/a"' in page and '"key": "p/b"' in page)
        check("and no lean field or value, even when the roster has one",
              "SECRET-LEAN" not in page and '"lean"' not in page)
        check("the data placeholder was replaced", "/*__DATA__*/null" not in page)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
