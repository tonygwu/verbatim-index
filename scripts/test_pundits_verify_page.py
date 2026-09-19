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
                                roster=str(td / "r.json"), out=str(td / "o.html")))
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
