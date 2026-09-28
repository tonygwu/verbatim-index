#!/usr/bin/env python3
"""speaker_audit_page.py builds a blind speaker-check page for leaders and predictions.

Synthetic data only, in a temporary git checkout. Proves: a blinded leaders quote is
located in the open text; the per-recording cap takes every judge in turn rather than
spending itself on the one with the strongest signal; a judge far from the others'
share is marked; prediction offsets map to exactly the quoted words, and an offset
that does not reproduce the quote stops the build; no judge, extractor or verifier
claim reaches the page; and the local server accepts the page it produced.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import speaker_audit_page as A  # noqa: E402
from pundits_verify_serve import page_ids  # noqa: E402

FAILED = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILED.append(name)


OPEN = ("[00:00:05] Welcome everyone, I am the host and Jane Roe runs Acme. >> Thanks for having me. "
        "I think the grid will run out of power before the chips run out. [00:01:10] "
        ">> Do you really believe that? >> I do, and we will ship ten gigawatts by 2030 at Acme. "
        "The host laughs here. >> Well I think you are wrong about the grid entirely.")


def grade(judge, share, quotes):
    return {"leader_slug": "jane-roe", "source_id": "talk-1", "judge": judge, "mode": "blinded", "run": 0,
            "validation_errors": [], "grade": {"subject_speech_share_pct": share, "dimensions": {
                "d1_clarity": {"evidence": [{"quote": q, "timestamp": "[00:00:05]"} for q in quotes]}}}}


def make_data(root: Path, prediction_offset_ok=True, video=True):
    (root / "roster").mkdir(parents=True)
    (root / "roster" / "final.json").write_text(json.dumps({"roster": [
        {"slug": "jane-roe", "name": "Jane Roe", "role": "CEO, Acme"}]}))
    (root / "transcripts_open" / "jane-roe").mkdir(parents=True)
    rec = {"leader_slug": "jane-roe", "source_id": "talk-1", "text": OPEN, "yt_title": "Talk",
           "yt_duration_sec": 600, **({"video_id": "vid1"} if video else {})}
    (root / "transcripts_open" / "jane-roe" / "talk-1.json").write_text(json.dumps(rec))
    for judge, share, quotes in (
            ("astra", 60, ["I think the grid will run out of power before the chips run out.",
                           "we will ship ten gigawatts by 2030 at [COMPANY]"]),
            ("fable", 58, ["I think the grid will run out of power before the chips run out.",
                           "we will ship ten gigawatts by 2030 at [COMPANY]"]),
            # The dissenting judge credits the host's lines, with strong signals, to the subject.
            ("gemini", 95, ["Welcome everyone, I am the host and [SUBJECT] runs [COMPANY]",
                            "Do you really believe that?",
                            "Well I think you are wrong about the grid entirely."])):
        d = root / "grades" / judge / "jane-roe"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"talk-1__{judge}__blinded__r0.json").write_text(json.dumps(grade(judge, share, quotes)))
    q = "we will ship ten gigawatts by 2030"
    start = OPEN.index(q)
    base = {"leader_slug": "jane-roe", "source_id": "talk-1", "transcript_id": "jane-roe/talk-1",
            "extraction": {"gates": {"own_voice": True}, "served_model": "m1", "gate_notes": "EXTRACTOR-NOTE"},
            "verification": {"attribution": "subject", "served_model": "m2", "notes": "VERIFIER-NOTE"},
            "prediction": {"normalized_claim": "CLAIM-TEXT"}}
    good = {**base, "prediction_id": "p1", "accepted": True,
            "source": {"quote": q, "quote_original": q if prediction_offset_ok else "something else",
                       "quote_char_start": start, "quote_char_end": start + len(q)}}
    rejected = {**base, "prediction_id": "p2", "accepted": False,
                "source": {"quote": "Thanks for having me.", "quote_original": "Thanks for having me.",
                           "quote_char_start": OPEN.index("Thanks"), "quote_char_end": OPEN.index("Thanks") + 21}}
    (root / "predictions" / "jane-roe").mkdir(parents=True)
    (root / "predictions" / "jane-roe" / "talk-1.jsonl").write_text(
        json.dumps(good) + "\n" + json.dumps(rejected) + "\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
                   check=True)


def run(root: Path, study: str, cap=2):
    out = root / "session" / study / "speaker_check.html"
    A.build(SimpleNamespace(study=study, data=str(root), keys="jane-roe/talk-1", out=str(out),
                            reasons=None, cap=cap))
    page = out.read_text()
    key = json.loads((out.parent / "quote_key.json").read_text())
    data = json.loads(page.split("const D = ", 1)[1].split(";\n", 1)[0].replace("<\\/", "</"))
    return out, page, key, data


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make_data(root)

        print("[LEADERS]")
        out, page, key, data = run(root, "leaders", cap=2)
        judges = {j["judge"] for v in key.values() for j in v["judges"]}
        check("a cap of 2 still reaches a quote from more than the strongest-signal judge",
              "gemini" in judges and judges & {"astra", "fable"})
        quotes = data["quote_rows"][0]["quotes"]
        gem = [v for v in key.values() if any(j["judge"] == "gemini" for j in v["judges"])]
        check("the judge 35 points from the others is marked dissenting",
              gem and all("dissenting_judge" in v["signals"] for v in gem))
        tokens = OPEN.split()
        check("each card's word offsets hold exactly its quote text",
              all(" ".join(t for t in tokens[c["quote_start"]:c["quote_end"]] if not A.MARK.fullmatch(t))
                  == " ".join(c["text"].split()) for c in quotes))
        man = json.loads((out.parent / "manifest.json").read_text())
        rep = man["recordings"]["jane-roe/talk-1"]
        check("every quote, including one with [SUBJECT] and [COMPANY], is located in the open text",
              rep["cited"] == 7 and rep["located"] == 7 and rep["not_located"] == 0)
        check("the manifest reports what the cap cut", rep["distinct_quotes"] == 5 and rep["shown"] == 2
              and rep["cut_by_cap"] == 3)
        check("the manifest pins the data revision and every input's hash",
              len(man["data_revision"]) == 40 and len(man["inputs_sha256"]) == 4)
        check("no judge name or claimed speaker reaches the page",
              not any(s in page for s in ("gemini", "astra", "fable", "claimed_speaker", "dissenting")))
        side = json.loads((out.with_suffix(".transcripts") / "jane-roe" / "talk-1.json").read_text())
        check("the range editor gets no model suggestion", side["suggestions"] == [])
        ids = page_ids(page)
        check("the local server accepts every quote on the page", ids["attribution"] == set(key)
              and ids["spans"] == {"jane-roe/talk-1"})
        check("the page is titled for its board", "<title>Leaders Speaker Check</title>" in page
              and "/*__" not in page)

        print("\n[PREDICTIONS]")
        out, page, key, data = run(root, "predictions", cap=6)
        check("only the accepted prediction is shown", set(key) == {"p1"})
        c = data["quote_rows"][0]["quotes"][0]
        check("character offsets map to exactly the quoted words",
              " ".join(tokens[c["quote_start"]:c["quote_end"]]) == "we will ship ten gigawatts by 2030")
        check("the extractor and verifier claims stay in the key, not the page",
              not any(s in page for s in ("EXTRACTOR-NOTE", "VERIFIER-NOTE", "CLAIM-TEXT", "m1", "m2"))
              and key["p1"]["judges"][1]["claimed_speaker"] == "subject")

    for label, kwargs, study in (("an offset that does not reproduce quote_original", {"prediction_offset_ok": False}, "predictions"),
                                 ("a recording with no video to listen to", {"video": False}, "leaders")):
        with tempfile.TemporaryDirectory() as td:
            make_data(Path(td), **kwargs)
            try:
                run(Path(td), study)
                refused = False
            except SystemExit as exc:
                refused = "REFUSING" in str(exc)
            check(f"{label} stops the build", refused)

    print(f"\n{'FAILED ' + str(len(FAILED)) if FAILED else 'all passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
