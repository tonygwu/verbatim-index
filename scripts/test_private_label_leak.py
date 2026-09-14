#!/usr/bin/env python3
"""A private lean label never reaches a judge prompt, the blinded text, or the published page.

Pundits plan, Verification. Lean labels are private: they stratify the
schedule and feed bias diagnostics, and nothing a judge reads or a visitor sees
may carry them. A planted canary string stands in for a label.

  PROMPT     both modes of the real PROMPT.md, rendered from a roster entry
             carrying the canary in every lean field, omit it
  BLINDING   the blinded transcript for that entry omits it
  SITE       the pundits page rendered from results carrying the canary in a
             person's lean fields and in diagnostics omits it
  READERS    only the schedule and roster tools (and tests) name the private
             lean files; a renderer that names them is caught, shown on a
             planted copy
  ROSTER     the real pundits roster, when present, carries no lean field

No quota.

  .venv/bin/python scripts/test_private_label_leak.py
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []
CANARY = "LEANCANARY7f3a9c"
PRIVATE_NAMES = re.compile(r"lean_labels|lean_sources|lean_notes|private/")
# schedule.py stratifies by lean; pundits_roster.py validates the labels;
# p3_judge_probe.py only PLANTS a fake canary named lean_labels_canary.json in its
# jail and never opens the real file.
ALLOWED_READERS = {"schedule.py", "pundits_roster.py", "p3_judge_probe.py"}


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def readers(scripts_dir: Path) -> set[str]:
    """Non-test scripts that name a private lean file."""
    out = set()
    for p in sorted(scripts_dir.iterdir()):
        if p.suffix not in (".py", ".sh") or p.name.startswith("test_"):
            continue
        if PRIVATE_NAMES.search(p.read_text(errors="replace")):
            out.add(p.name)
    return out


def main() -> int:
    print("private lean label leak")
    import grading_contract as GC
    import normalize_transcripts as N
    import build_study_site as B

    profile = json.loads((REPO / "profiles" / "pundits.json").read_text())
    skill = REPO / profile["skill_dir"]
    person = {"slug": "p", "name": "Pat Example", "role": "podcast host", "company": "The Pat Show",
              "show": "The Pat Show", "outlet": "Pat Media", "handles": ["PatX"], "own_channels": [],
              "identity_tokens": ["The Pat Show", "Pat Media"], "archival": False,
              "lean": CANARY, "lean_sources": [{"url": "https://x", "quote": CANARY}], "lean_notes": CANARY}
    text = "[00:00:00] Welcome to The Pat Show, I'm Pat Example. Today we argue about taxes. " * 40

    print("\n[BLINDING]")
    blinded, _ = N.blind_study(text, person, profile["blinding"], set())
    check("the blinded transcript omits the canary", CANARY not in blinded)

    print("\n[PROMPT]")
    rec = {"leader_slug": "p", "source_id": "s1", "text": blinded, "duration_sec": 3600, "declared_year": 2025,
           "word_count": len(blinded.split()), "_speaker_name": person["name"], "_speaker_role": person["role"]}
    values = GC.prompt_values(rec, (skill / "RUBRIC.md").read_text(), (skill / "judge_output.schema.json").read_text(), profile)
    template = (skill / "PROMPT.md").read_text()
    for mode in ("blinded", "open"):
        prompt = GC.render_prompt(template, mode, values)
        check(f"the {mode} prompt omits the canary", CANARY not in prompt)

    print("\n[SITE]")
    results = {"leaders": [{"slug": "p", "name": "Pat Example", "role": "podcast host", "rank": 1, "lean": CANARY,
                            "lean_group": CANARY, "blinded": {"overall": 60.0, "ci_low": 55.0, "ci_high": 65.0},
                            "open": {"overall": 62.0}, "halo": {"overall": 2.0}, "n_transcripts": 12,
                            "confidence": "high"}],
               "unranked": [], "diagnostics": {"grades_used": 72, "judge_by_lean": {CANARY: 1.0}}}
    page = B.render(results, profile, B.load_copy(profile), "14 September 2026")
    check("the page renders the person", "Pat Example" in page)
    check("the page omits the canary", CANARY not in page)

    print("\n[READERS]")
    found = readers(REPO / "scripts")
    check("only the schedule and roster tools name the private lean files", found <= ALLOWED_READERS,
          f"unexpected readers: {sorted(found - ALLOWED_READERS)}")
    with tempfile.TemporaryDirectory() as td:
        planted = Path(td)
        (planted / "build_study_site.py").write_text("labels = json.load(open('data-pundits/private/lean_labels.json'))\n")
        (planted / "test_something.py").write_text("open('data-pundits/private/lean_labels.json')\n")
        caught = readers(planted)
        check("a renderer that names the label file is caught, and a test that does is not",
              caught == {"build_study_site.py"}, str(caught))

    print("\n[ROSTER]")
    roster_path = REPO / "data-pundits" / "roster" / "final.json"
    if roster_path.exists():
        roster = json.loads(roster_path.read_text())["roster"]
        leaked = [p["slug"] for p in roster if any(k.startswith("lean") for k in p)]
        check(f"the real roster ({len(roster)} people) carries no lean field", not leaked, str(leaked))
    else:
        print("  SKIP  no data-pundits roster in this clone")

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
