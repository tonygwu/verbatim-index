#!/usr/bin/env python3
"""The specs must tell both models how to WRITE a resolution criterion.

Two defects in the published corpus trace to one shared line, and both are spec
defects rather than model failures (docs/PREDICTIONS-CRITERIA-AGREEMENT.md):

  - ELIGIBILITY.md G2 said: write "By <date>, <observable> will / will not
    <threshold>." The "will / will not" means "choose one" and was copied
    verbatim into 18 verifier criteria, which are then unresolvable either way.
  - The same field was described three different ways in three files, and none
    stated the polarity convention, so on a prediction that is itself negative
    the two models picked opposite conventions. 8 pairs in the corpus assert
    opposite outcomes for the same quote.

This test pins the repair. It reads the shipped specs as text, because a model
reads them as text; nothing here imports the pipeline.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
SKILL = ROOT / ".claude" / "skills" / "prediction-extractor"
FAILED = []

# Any form that leaves the direction open. The prose may NAME these to forbid them, so a
# mention is only a failure when it is given as a template to write.
# Whitespace is \s+ throughout: the old ELIGIBILITY.md wrapped the template as
# "will / will\n  not <threshold>", which a pattern with a literal space walks straight past.
UNDIRECTED = re.compile(r"will\s*/\s*will\s+not|will\s+not\s*/\s*will|will\s+or\s+will\s+not", re.I)
SPEC_FILES = ["ELIGIBILITY.md", "EXTRACTION.md", "VERIFICATION.md"]
SCHEMAS = ["extractor_output.schema.json", "verifier_output.schema.json", "prediction_record.schema.json"]


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def criterion_description(path: pathlib.Path) -> str:
    """The resolution_criteria description a model is shown, from a hand-formatted schema."""
    node = json.loads(path.read_text())

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "resolution_criteria" and isinstance(v, dict) and "description" in v:
                    return v["description"]
                found = walk(v)
                if found:
                    return found
        elif isinstance(o, list):
            for v in o:
                found = walk(v)
                if found:
                    return found
        return None

    got = walk(node)
    assert got, f"{path.name} has no resolution_criteria description"
    return got


def main() -> int:
    for name in SCHEMAS:
        p = SKILL / name
        try:
            json.loads(p.read_text())
            ok = True
        except json.JSONDecodeError as e:
            ok, err = False, str(e)
        check(f"JSON: {name} parses", ok, err if not ok else "")
    if FAILED:
        print("\n%d failed" % len(FAILED))
        return 1

    # --- no template hands a model an undirected criterion ---
    for name in SPEC_FILES:
        text = (SKILL / name).read_text()
        offenders = [m.group(0) for m in UNDIRECTED.finditer(text)]
        # ELIGIBILITY.md must name the form in order to forbid it; every mention there has to
        # sit in the paragraph that says "Never write".
        allowed = name == "ELIGIBILITY.md" and "Never write" in text
        check(f"TEMPLATE: {name} hands no model a 'will / will not' criterion template",
              not offenders or allowed, str(offenders))
    for name in SCHEMAS:
        d = criterion_description(SKILL / name)
        bare = UNDIRECTED.search(d) and "never" not in d.lower()
        check(f"TEMPLATE: {name}'s criterion description is not an undirected template", not bare, d)

    # --- the polarity convention is stated, and stated the same way everywhere ---
    elig = (SKILL / "ELIGIBILITY.md").read_text()
    check("POLARITY: ELIGIBILITY.md states that TRUE means the speaker was RIGHT",
          re.search(r"TRUE means the speaker was RIGHT", elig) is not None)
    check("POLARITY: ELIGIBILITY.md says to keep the speaker's own negation rather than flip it",
          "negation" in elig and re.search(r"do not flip", elig, re.I) is not None)
    check("POLARITY: ELIGIBILITY.md forbids writing the falsification condition as the criterion",
          re.search(r"never its falsification", elig, re.I) is not None, elig[:0])
    check("POLARITY: no schema still describes the criterion as what would show the claim WRONG",
          not any(re.search(r"would show the claim wrong", criterion_description(SKILL / n), re.I)
                  for n in SCHEMAS),
          str({n: criterion_description(SKILL / n)[:70] for n in SCHEMAS}))

    descs = {n: criterion_description(SKILL / n) for n in SCHEMAS}
    check("ALIGNED: all three schemas point at one rule instead of describing three",
          all("ELIGIBILITY.md G2" in d for d in descs.values()),
          str({n: d[-40:] for n, d in descs.items()}))
    check("ALIGNED: all three carry the polarity sentence, not just the extractor's",
          all("TRUE means the speaker was RIGHT" in d for d in descs.values()),
          str({n: d for n, d in descs.items() if "TRUE means the speaker was RIGHT" not in d}))

    # --- the pinned release matches the files, or every run fails at startup ---
    sys.path.insert(0, str(ROOT / "scripts"))
    import predictions_lib as L
    ex = L._contract(SKILL / "EXTRACTION.md", SKILL / "extractor_output.schema.json")["contract_id"]
    ve = L._contract(SKILL / "VERIFICATION.md", SKILL / "verifier_output.schema.json")["contract_id"]
    pinned = json.loads((SKILL / "POLICY_RELEASE.json").read_text())
    check("RELEASE: POLICY_RELEASE.json pins the contracts these files actually yield",
          pinned["contracts"] == {"extract": ex, "verify": ve},
          f"pinned {pinned['contracts']}, files yield {{'extract': '{ex}', 'verify': '{ve}'}}")
    check("RELEASE: editing a spec without bumping the release fails loudly",
          L.load_policy_release(SKILL)["release"] == pinned["release"])

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
