#!/usr/bin/env python3
"""The pundit-transcript-grader skill: rubric, schema and prompt agree with the profile.

Pundits plan, P5a. Contract v2 refuses every pundits grading run until
.claude/skills/pundit-transcript-grader holds RUBRIC.md, judge_output.schema.json
and PROMPT.md. These checks make sure the three files describe the same rubric
the profile scores and grade_one validates, so a judge is never asked for one
shape and graded against another.

  CONTRACT    contract_v2 computes for the real pundits profile
  SCHEMA      dimension keys, sub-criterion codes and the venue enum match the
              profile and the plan; every field validate_v2 enforces is required
  CANNED      a well-formed grade carries every required field and passes validate_v2
  PROMPT      only known placeholders; both modes render; the modes differ only
              in the identity branch; the blinded mode never names the speaker
  RUBRIC      every sub-criterion code, the dimension weights computed from the
              profile, and the plan's observability and precedence rules appear

No quota.

  .venv/bin/python scripts/test_pundit_skill.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
SKILL = REPO / ".claude" / "skills" / "pundit-transcript-grader"
PASS, FAIL = [], []
# Five broad venues (operator, 2026-09-15): nine fine venues could not be applied
# consistently by the operator, Fable or Sonnet (Sonnet matched exact venue 21/37).
VENUES = ["solo", "reaction", "conversation", "debate", "speech"]


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def canned(prof: dict, tid: str) -> dict:
    dims, subs = {}, []
    for d in prof["scoring"]["dimensions"]:
        dims[d["key"]] = {"dimension_status": "supported", "score": 62,
                          "reasoning": "The subject restated the opposing case in its own terms before answering it, "
                                       "and conceded one factual point when pressed by the host.",
                          "evidence": [{"quote": "the strongest version of their argument is this", "timestamp": "[00:12:04]",
                                        "speaker": "subject", "why_it_matters": "states the other side first"},
                                       {"quote": "fair point, I had that wrong", "timestamp": "[00:31:40]",
                                        "speaker": "subject", "why_it_matters": "concedes when warranted"}],
                          "counterevidence": "Later the subject called a critic's motives cynical without citing anything."}
        subs += [{"code": c, "score": 3, "justification": "observed once"} for c in d["subcriteria"]]
    weights = {d["key"]: d["weight"] for d in prof["scoring"]["dimensions"]}
    return {"schema_version": "pundits-1.0", "transcript_id": tid, "venue_type": "conversation",
            "venue_challenge": 3, "venue_challenge_reason": "The host pressed twice on specifics.",
            "subject_speech_share_pct": 55, "attribution_confidence": "medium",
            "attribution_notes": "Turns separated by question marks and names.",
            "identity_guess": "unknown", "identity_confident": False, "identity_basis": "No names survive.",
            "asr_quality": "minor_corruption", "asr_notes": "none",
            "subcriteria": subs, "dimensions": dims,
            "overall": round(sum(weights[k] * 62 for k in weights), 2), "coverage": 1.0,
            "confidence": "medium", "confidence_reason": "One long recording.",
            "salient_claims": ["The subject argued a policy's costs outweigh its benefits."], "red_flags": []}


def main() -> int:
    print("pundit-transcript-grader skill")
    import grading_contract as GC
    prof = json.loads((REPO / "profiles" / "pundits.json").read_text())
    missing = [n for n in GC.SKILL_FILES if not (SKILL / n).is_file()]
    check("the skill directory holds RUBRIC.md, judge_output.schema.json and PROMPT.md", not missing, f"missing {missing}")
    if missing:
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1

    print("\n[CONTRACT]")
    try:
        contract = GC.contract_v2(prof)
        check("contract_v2 computes for the real pundits profile", len(contract["contract_id"]) == 16)
    except RuntimeError as exc:
        check("contract_v2 computes for the real pundits profile", False, str(exc))

    print("\n[SCHEMA]")
    schema = json.loads((SKILL / "judge_output.schema.json").read_text())
    keys = [d["key"] for d in prof["scoring"]["dimensions"]]
    codes = [c for d in prof["scoring"]["dimensions"] for c in d["subcriteria"]]
    dim_schema = schema["properties"]["dimensions"]
    check("schema dimension keys equal the profile's", sorted(dim_schema["required"]) == sorted(keys),
          str(dim_schema["required"]))
    check("schema lists every sub-criterion code, in order",
          " ".join(codes) in schema["properties"]["subcriteria"]["description"])
    check("schema venue enum matches the plan", schema["properties"]["venue_type"]["enum"] == VENUES,
          str(schema["properties"]["venue_type"]["enum"]))
    dim_def = schema["$defs"]["dimension"]
    check("a dimension requires dimension_status, score, reasoning, evidence and counterevidence",
          set(dim_def["required"]) >= {"dimension_status", "score", "reasoning", "evidence", "counterevidence"},
          str(dim_def["required"]))
    check("dimension_status is supported or unsupported",
          dim_def["properties"]["dimension_status"]["enum"] == ["supported", "unsupported"])
    check("a dimension score may be null, for an unsupported dimension",
          "null" in dim_def["properties"]["score"]["type"])
    ev = dim_def["properties"]["evidence"]["items"]
    check("each evidence quote names its speaker as subject, interlocutor or clip",
          "speaker" in ev["required"] and ev["properties"]["speaker"]["enum"] == list(GC.EVIDENCE_SPEAKERS))
    check("overall may be null", "null" in schema["properties"]["overall"]["type"])

    print("\n[CANNED]")
    g = canned(prof, "pundit-p/s1")
    absent = [k for k in schema["required"] if k not in g]
    check("a well-formed grade carries every required top-level field", not absent, f"absent {absent}")
    errs = GC.validate_v2(g, "pundit-p/s1", prof["scoring"])
    check("and passes validate_v2", errs == [], str(errs))
    g2 = json.loads(json.dumps(g))
    g2["dimensions"][keys[0]]["evidence"][0]["speaker"] = "narrator"
    check("an evidence speaker outside the enum fails validate_v2",
          bool(GC.validate_v2(g2, "pundit-p/s1", prof["scoring"])))

    print("\n[PROMPT]")
    template = (SKILL / "PROMPT.md").read_text()
    used = set(re.findall(r"\{\{([a-z_]+)\}\}", template))
    check("PROMPT.md uses only known placeholders", used <= set(GC.PLACEHOLDERS), str(used - set(GC.PLACEHOLDERS)))
    check("it uses the rubric, schema, transcript, id, metadata and speaker placeholders",
          {"rubric", "schema", "transcript", "transcript_id", "metadata", "speaker_name"} <= used, str(used))
    rec = {"leader_slug": "pundit-p", "source_id": "s1", "text": "[00:00:01] we talked", "declared_kind": "podcast",
           "declared_year": 2025, "duration_sec": 3600, "word_count": 3, "_speaker_name": "Pat Undit"}
    vals = GC.prompt_values(rec, "RUBRIC-TEXT", "SCHEMA-TEXT", prof)
    try:
        blinded = GC.render_prompt(template, "blinded", vals)
        opened = GC.render_prompt(template, "open", vals)
        rendered = True
    except RuntimeError as exc:
        rendered, blinded, opened = False, "", ""
        print(f"        {exc}")
    check("both modes render", rendered)
    check("the blinded prompt never names the speaker", "Pat Undit" not in blinded)
    check("the open prompt names the speaker", "Pat Undit" in opened)
    common = [line for line in blinded.splitlines() if line in opened.splitlines()]
    only_b = [line for line in blinded.splitlines() if line not in opened.splitlines()]
    only_o = [line for line in opened.splitlines() if line not in blinded.splitlines()]
    check("the modes share the rubric, schema, metadata and transcript",
          all(x in "\n".join(common) for x in ("RUBRIC-TEXT", "SCHEMA-TEXT", vals["metadata"].splitlines()[0],
                                               "[00:00:01] we talked")))
    check("and differ only in a short identity branch", len(only_b) <= 8 and len(only_o) <= 8,
          f"blinded-only {len(only_b)}, open-only {len(only_o)}")

    print("\n[RUBRIC]")
    rubric = (SKILL / "RUBRIC.md").read_text()
    for c in codes:
        check(f"rubric defines {c}", re.search(rf"\b{c}\b", rubric) is not None)
    for d in prof["scoring"]["dimensions"]:
        check(f"rubric gives {d['key']} its weight {round(d['weight'] * 100)}%",
              f"{round(d['weight'] * 100)}%" in rubric and d["key"] in rubric)
    for phrase in ("not_observed", "unsupported", "not a fact-check", "S4", "G4", "affiliation", "interlocutor", "clip"):
        check(f"rubric covers {phrase!r}", phrase in rubric)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
