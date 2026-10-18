#!/usr/bin/env python3
"""`annotations.py` migrates, verifies, rebuilds and exports a session without losing an answer.

Synthetic data only, in temporary git checkouts. Proves:

  MIGRATE   an old-format session (speaker_check.html, quote_key.json, a version-1
            manifest) is adopted by writing manifest.json and nothing else; a second
            run does nothing; with no version-1 manifest, --project is required
  VERIFY    passes on the adopted session; fails on a wrong answers sha256 and on a
            speaker range the transcript cannot hold; never writes the answers file
  REBUILD   renders the page again and changes nothing but the page; sidecars and
            answers are byte-identical, and verify still passes
  EXPORT    quotes reproduce the old import's quote_results.json; a two-project
            session refuses `export quotes` without --project and splits with it
  PUBLIC    a session written into this public repository is refused

  .venv/bin/python scripts/test_annotations_cli.py
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import annotations as C  # noqa: E402
from annotations_page import join_quotes, page_payload  # noqa: E402
from annotations_spans import build_transcript, reconcile_quote_reviews, sidecar_path  # noqa: E402
from test_annotations_select import make_data  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def git(root, *args) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def commit(root):
    git(root, "add", "-A")
    git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            code = C.main(argv)
        except SystemExit as exc:
            return (exc.code if isinstance(exc.code, int) else 1), str(exc)
    return code, out.getvalue()


RAW = ("[00:00:05] Welcome to the show today >> I think the grid will run out of power first "
       ">> do you really believe that? >> I do and we will ship it by 2030")


def legacy_session(root: Path) -> Path:
    """A leaders-board session exactly as the 2026-09-27 builder left one."""
    s = root / "leaders"
    page = s / "speaker_check.html"
    key = "jane-roe/talk-1"
    side = build_transcript(key, RAW, [])
    sidecar_path(page, key).parent.mkdir(parents=True)
    sidecar_path(page, key).write_text(json.dumps(side, ensure_ascii=False))
    quote = {"qid": "jane-roe:talk-1:7", "t": 0, "start": 0, "end": 14, "quote_start": 7, "quote_end": 14,
             "before": "", "text": "I think the grid will run out", "after": ""}
    data = {"rows": [], "quote_rows": [{"key": key, "slug": "jane-roe", "sid": "talk-1", "person": "Jane Roe",
                                        "role": "", "title": "T", "channel": "", "upload": "", "video_id": "v",
                                        "duration": 60, "forms": ["Jane Roe"], "quotes": [quote]}],
            "venues": [], "transcript_index": {key: {"text_sha256": side["text_sha256"],
                                                     "token_count": side["token_count"]}}}
    page.write_text("<title>Leaders Speaker Check</title><script>\nconst D = " + page_payload(data)
                    + ";\nconst artifactStore = {};\n</script>\n")
    answers = {"labels": {}, "attribution": {}, "spans": {key: {
        "schema_version": 1, "key": key, "text_sha256": side["text_sha256"], "token_count": side["token_count"],
        "ranges": [{"start": 7, "end": 14, "speaker": "subject", "origin": "human"}], "checked_by": "operator",
        "updated_at": "2026-09-28T00:00:00Z", "assisted": True, "suggestions_sha256": side["suggestions_sha256"]}},
        "corrections": {}}
    answers = reconcile_quote_reviews(answers, page, data["quote_rows"])
    (s / "human_answers.json").write_text(json.dumps(answers, indent=1, ensure_ascii=False) + "\n")
    key_map = {"jane-roe:talk-1:7": {"key": key, "board": "leaders", "signals": ["recording_selected"],
                                     "judges": [{"judge": "j1", "claimed_speaker": "subject"}]}}
    (s / "quote_key.json").write_text(json.dumps(key_map, indent=1) + "\n")
    docs = [dict(v, qid=k) for k, v in answers["attribution"].items()]
    (s / "quote_results.json").write_text(json.dumps(join_quotes(docs, key_map), indent=1, ensure_ascii=False) + "\n")
    (s / "manifest.json").write_text(json.dumps({"schema_version": 1, "study": "leaders", "cap_per_recording": 6,
                                                 "data_revision": "0" * 40, "code_revision": "1" * 40,
                                                 "inputs_sha256": {}, "recordings": {key: {"cited": 1}},
                                                 "blind": "no model suggestion"}) + "\n")
    return s


def main() -> int:
    print("annotations CLI")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "data"
        root.mkdir()
        s = legacy_session(root)
        git(root, "init", "-q")
        commit(root)
        answers_sha = sha(s / "human_answers.json")
        sidecars = sha(sidecar_path(s / "speaker_check.html", "jane-roe/talk-1"))

        print("\n[MIGRATE]")
        code, out = run(["migrate", "--session", str(s)])
        changed = git(root, "status", "--porcelain").split()
        check("migrate adopts the session", code == 0, out)
        check("and changes manifest.json and nothing else", changed == ["M", "data/leaders/manifest.json"]
              or changed == ["M", "leaders/manifest.json"], str(changed))
        man = json.loads((s / "manifest.json").read_text())
        check("the version-1 study `leaders` becomes the project `insights`, and the old manifest is kept whole",
              man["projects"] == ["insights"] and man["legacy_from"]["manifest"]["study"] == "leaders"
              and man["recordings"]["jane-roe/talk-1"]["cited"] == 1 and man["files"]["page"] == "speaker_check.html",
              json.dumps(man)[:300])
        code, out = run(["migrate", "--session", str(s)])
        check("a second migrate does nothing", code == 0 and "nothing to do" in out, out)
        commit(root)

        print("\n[VERIFY]")
        code, out = run(["verify", "--session", str(s), "--expect-answers-sha256", answers_sha])
        rep = json.loads(out)
        check("verify passes on the adopted session, every check", code == 0 and rep["ok"],
              str([c for c in rep["checks"] if not c["ok"]]))
        check("including the export that reproduces quote_results.json and a live server read",
              any(c["check"] == "export quotes reproduces quote_results.json" and c["ok"] for c in rep["checks"])
              and any("server's answers equal" in c["check"] and c["ok"] for c in rep["checks"]))
        code, out = run(["verify", "--session", str(s), "--expect-answers-sha256", "0" * 64])
        check("verify fails on a wrong answers sha256", code == 1 and json.loads(out)["ok"] is False)
        bad = json.loads((s / "human_answers.json").read_text())
        bad["spans"]["jane-roe/talk-1"]["ranges"][0]["end"] = 999
        (s / "human_answers.json").write_text(json.dumps(bad, indent=1) + "\n")
        code, out = run(["verify", "--session", str(s)])
        failed = [c["check"] for c in json.loads(out)["checks"] if not c["ok"]]
        check("verify fails on a speaker range the transcript cannot hold",
              code == 1 and "every speaker annotation validates against its transcript" in failed, str(failed))
        git(root, "checkout", "--", "leaders/human_answers.json")
        check("and verify never wrote the answers file", sha(s / "human_answers.json") == answers_sha)

        print("\n[REBUILD]")
        code, out = run(["rebuild", "--session", str(s)])
        changed = git(root, "status", "--porcelain").split()
        check("rebuild changes the page and nothing else", code == 0 and changed == ["M", "leaders/speaker_check.html"],
              f"{out} {changed}")
        page = (s / "speaker_check.html").read_text()
        check("the rebuilt page has the session block and no Artifact store",
              '"session": {' in page and "artifactStore" not in page and "<title>Annotations · insights</title>" in page)
        code, out = run(["verify", "--session", str(s), "--expect-answers-sha256", answers_sha])
        check("verify still passes after rebuild", code == 0 and json.loads(out)["ok"])
        check("answers and sidecars are byte-identical",
              sha(s / "human_answers.json") == answers_sha
              and sha(sidecar_path(s / "speaker_check.html", "jane-roe/talk-1")) == sidecars)

        print("\n[MIGRATE without a version-1 manifest]")
        bare = root / "bare"
        (bare / "speaker_check.transcripts").mkdir(parents=True)
        for f in ("speaker_check.html", "human_answers.json", "quote_key.json"):
            (bare / f).write_bytes((s / f).read_bytes())
        (bare / "speaker_check.transcripts").joinpath("jane-roe").mkdir()
        (bare / "speaker_check.transcripts" / "jane-roe" / "talk-1.json").write_bytes(
            sidecar_path(s / "speaker_check.html", "jane-roe/talk-1").read_bytes())
        code, out = run(["migrate", "--session", str(bare)])
        check("with no version-1 manifest, migrate asks for --project rather than guessing",
              code != 0 and "pass --project" in out, out)
        code, out = run(["migrate", "--session", str(bare), "--project", "predictions"])
        check("and with it, adopts the session", code == 0 and json.loads(
            (bare / "manifest.json").read_text())["projects"] == ["predictions"], out)

    with tempfile.TemporaryDirectory() as td:
        lead = Path(td)
        make_data(lead)
        print("\n[EXPORT]")
        out_dir = lead / "both"
        with contextlib.redirect_stdout(io.StringIO()):
            C.build(SimpleNamespace(project=["insights", "predictions"], data=str(lead), keys="jane-roe/talk-1",
                                    out=str(out_dir), name=None, reasons=None, cap=6, checklist=None,
                                    grades=False, drafts=None))
        code, out = run(["verify", "--session", str(out_dir)])
        check("a freshly built two-project session verifies", code == 0 and json.loads(out)["ok"],
              str([c for c in json.loads(out)["checks"] if not c["ok"]]) if code == 0 or out.startswith("{") else out)
        code, out = run(["export", "quotes", "--session", str(out_dir), "--out", str(lead / "q.json")])
        check("export quotes without --project refuses a two-project session", code != 0 and "--project" in out, out)
        code, out = run(["export", "quotes", "--session", str(out_dir), "--project", "predictions",
                         "--out", str(lead / "q.json")])
        got = json.loads((lead / "q.json").read_text())
        check("with --project it exports that project's quotes only",
              code == 0 and got["unanswered"] == ["p1"], str(got["unanswered"]))

        print("\n[PUBLIC]")
        target = REPO / "annotations-refused-session"
        code, out = run(["build", "--project", "insights", "--data", str(lead), "--keys", "jane-roe/talk-1",
                         "--out", str(target)])
        check("a session inside the public repository is refused, and nothing is written",
              code != 0 and "public repository" in out and not target.exists(), out)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
