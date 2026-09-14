#!/usr/bin/env python3
"""Pundits blinding: name, handles, show and outlet go; the ordinary English they collide with stays.

Pundits plan, P5b. blind() knows one company string and the leaders tokens.
A pundit is identified by a real name, one or more handles ("Destiny"), a show
("The Destiny Show") and an outlet ("Twitch"), several of which are also
ordinary English words. blind_study() takes the tokens and the affiliation
fields from the study profile, applies every form in ONE longest-first pass so a
show name containing the handle is replaced whole, and redacts a single-word
form that is an ordinary English word only where it is capitalised.

  NAME         the full name, the surname and its possessive become [SUBJECT]
  HANDLE       the capitalised handle becomes [SUBJECT]; lowercase "destiny" survives
  AFFILIATION  the whole show name becomes [AFFILIATION], not "The [SUBJECT] Show";
               the capitalised outlet goes, lowercase "twitch" survives
  ASR          a speech-recognition corruption of the surname becomes [SUBJECT]
  TOKENS       no leaders [COMPANY] token appears, and every substitution is counted
  REAL-RUN     normalize_transcripts.py --study pundits blinds a pundits checkout

No quota, no live data.

  .venv/bin/python scripts/test_pundits_blinding.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PY = sys.executable
PASS, FAIL = [], []

PERSON = {"slug": "steven-bonnell", "name": "Steven Bonnell", "handles": ["Destiny"],
          "show": "The Destiny Show", "outlet": "Twitch", "role": "streamer"}
TEXT = ("[00:00:01] Welcome back to The Destiny Show, streaming live on Twitch. "
        "Steven Bonnell here. Bonnell's view is simple. Destiny thinks the argument fails. "
        "I believe in free will, not destiny, and I felt a twitch of doubt. "
        "Stephen Bonel said it again later.")


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load():
    spec = importlib.util.spec_from_file_location("norm_p5b", REPO / "scripts" / "normalize_transcripts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    print("pundits blinding")
    N = load()
    if not hasattr(N, "blind_study"):
        check("normalize_transcripts exposes blind_study", False)
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1
    blinding = json.loads((REPO / "profiles" / "pundits.json").read_text())["blinding"]
    dictionary = N.load_dictionary()
    out, counts = N.blind_study(TEXT, PERSON, blinding, dictionary, aliases=[])
    subj, aff = blinding["subject_token"], blinding["affiliation_token"]

    print("\n[NAME]")
    check("the full name is removed", "Steven Bonnell" not in out)
    check("the surname possessive is removed", "Bonnell's" not in out and "Bonnell" not in out)

    print("\n[HANDLE]")
    check("the capitalised handle is removed", "Destiny thinks" not in out and f"{subj} thinks" in out, out)
    check("the ordinary word 'destiny' survives", "not destiny," in out, out)

    print("\n[AFFILIATION]")
    check("the whole show name becomes the affiliation token",
          f"to {aff}, streaming" in out and f"The {subj} Show" not in out, out)
    check("the capitalised outlet becomes the affiliation token", f"on {aff}." in out, out)
    check("the ordinary word 'twitch' survives", "a twitch of doubt" in out, out)

    print("\n[ASR]")
    check("a corrupted surname is removed", "Bonel" not in out, out)

    print("\n[TOKENS]")
    check("no leaders [COMPANY] token appears", "[COMPANY]" not in out)
    check("affiliation substitutions are counted", any(k.startswith("affiliation") for k in counts), str(counts))
    check("name substitutions are counted", any(k.startswith("name") for k in counts), str(counts))

    print("\n[REAL-RUN]")
    with tempfile.TemporaryDirectory(prefix="p5b-") as td:
        root = Path(td).resolve() / "pundits-data"
        root.mkdir()
        for args in (("init", "-q", "-b", "main"),
                     ("config", "remote.origin.url", "git@github.com:tonygwu/verbatim-pundits-data.git")):
            subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
        (root / ".study").write_text("pundits\n")
        (root / "roster").mkdir()
        (root / "roster/final.json").write_text(json.dumps({"roster": [PERSON]}))
        src = root / "transcripts" / PERSON["slug"] / "s1.json"
        src.parent.mkdir(parents=True)
        src.write_text(json.dumps({"leader_slug": PERSON["slug"], "source_id": "s1", "text": TEXT, "word_count": 60}))
        env = {k: v for k, v in os.environ.items() if k != "STUDY"}
        r = subprocess.run([PY, REPO / "scripts/normalize_transcripts.py", "--study", "pundits", "--mode", "blinded",
                            "--transcripts", root / "transcripts", "--out", root / "transcripts_blind",
                            "--roster", root / "roster/final.json", "--log", root / "logs/normalize.json"],
                           env=env, capture_output=True, text=True)
        written = root / "transcripts_blind" / PERSON["slug"] / "s1.json"
        text = json.loads(written.read_text())["text"] if written.exists() else ""
        check("normalize --study pundits exits 0", r.returncode == 0, r.stderr[-400:])
        check("and writes a transcript blinded by name, handle, show and outlet",
              bool(text) and "Bonnell" not in text and "Destiny Show" not in text and aff in text, text[:200])

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
