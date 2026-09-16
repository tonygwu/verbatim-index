#!/usr/bin/env python3
"""Contract v2: what a pundits grade depends on, and when a stored one may be reused.

Pundits plan, P2. No judge is called: grade_one's judge function is replaced by
a stub that fails the test if it is reached when it should not be.

  CONTRACT-SCOPE  editing either mode branch of PROMPT.md, the weights, a judge
                  request setting or the wordlist bytes changes contract_id;
                  changing the domain, data link, site or description does not.
  RENDER          each mode keeps only its own branch, the two modes differ only
                  in that branch, an unknown placeholder is refused, and a
                  transcript containing "{{rubric}}" is inserted, not expanded.
  CACHE           a stored v2 grade is reused only when every identity field
                  matches; a stale one is reported naming the field and left
                  byte-identical; --force moves it aside and writes a stamped
                  replacement; a leaders (v1) job keeps its old behaviour.
  AGGREGATE       a real aggregate.py run refuses an all-obsolete corpus, a
                  grade from another study and a slug not on the roster, and
                  does not raise that refusal for a current corpus.

  .venv/bin/python scripts/test_pundits_contract.py
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PY = sys.executable
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


TEMPLATE = """Grade one transcript.
<<<BLINDED>>>
IDENTITY: withheld. Do not try to work out who is speaking.
<<<END>>>
<<<OPEN>>>
IDENTITY: Speaker: {{speaker_name}}
<<<END>>>
RUBRIC
{{rubric}}
METADATA
{{metadata}}
TRANSCRIPT {{transcript_id}}
{{transcript}}
Sub-criteria: {{subcriteria}}. Overall = {{overall_formula}}. Quotes up to {{max_quote_words}} words.
SCHEMA
{{schema}}
"""


def fixture_skill(root: Path) -> Path:
    sd = root / "skill"
    sd.mkdir(parents=True)
    (sd / "RUBRIC.md").write_text("fixture rubric\n")
    (sd / "judge_output.schema.json").write_text('{"type": "object"}\n')
    (sd / "PROMPT.md").write_text(TEMPLATE)
    return sd


def fixture_profile(sd: Path) -> dict:
    prof = json.loads((REPO / "profiles/pundits.json").read_text())
    prof["skill_dir"] = str(sd)
    return prof


REC = {"leader_slug": "pundit-p", "source_id": "s1", "text": "we disagree about this {{rubric}} point " * 30,
       "declared_kind": "podcast", "declared_year": 2025, "duration_sec": 3600, "word_count": 210,
       "_speaker_name": "Pat Undit"}


def test_contract_scope(tmp: Path) -> None:
    print("\n[CONTRACT-SCOPE]")
    import grading_contract as GC
    sd = fixture_skill(tmp / "scope")
    prof = fixture_profile(sd)
    base = GC.contract_v2(prof)["contract_id"]
    check("the contract is stable across two computations", GC.contract_v2(prof)["contract_id"] == base)

    def moved(mutate) -> bool:
        p = copy.deepcopy(prof)
        saved = {n: (sd / n).read_bytes() for n in GC.SKILL_FILES}
        try:
            mutate(p)
            return GC.contract_v2(p)["contract_id"] != base
        finally:
            for n, b in saved.items():
                (sd / n).write_bytes(b)

    check("editing the BLINDED branch of PROMPT.md changes it",
          moved(lambda p: (sd / "PROMPT.md").write_text(TEMPLATE.replace("withheld.", "withheld!"))))
    check("editing the OPEN branch of PROMPT.md changes it",
          moved(lambda p: (sd / "PROMPT.md").write_text(TEMPLATE.replace("Speaker:", "Speaker is:"))))
    check("editing RUBRIC.md changes it", moved(lambda p: (sd / "RUBRIC.md").write_text("other rubric\n")))
    check("editing the schema changes it",
          moved(lambda p: (sd / "judge_output.schema.json").write_text('{"type": "array"}\n')))

    def reweight(p):
        p["scoring"]["dimensions"][0]["weight"] = 0.40
        p["scoring"]["dimensions"][2]["weight"] = 0.25
    check("changing the weights changes it", moved(reweight))
    check("changing a judge's effort changes it",
          moved(lambda p: p["judge_requests"]["gemini"].update(effort="medium")))
    check("changing the identity treatment changes it",
          moved(lambda p: p["identity_treatment"]["metadata_fields"].append("word_count")
                if False else p["identity_treatment"].update(open_mode_adds=["speaker_name", "role"])))
    wl = tmp / "wordlist.json"
    wl.write_text('{"a": 1}')

    def with_wordlist(p):
        p["blinding"]["wordlist"] = str(wl)
    p2 = copy.deepcopy(prof)
    with_wordlist(p2)
    first = GC.contract_v2(p2)["contract_id"]
    wl.write_text('{"a": 2}')
    check("changing the wordlist BYTES changes it", GC.contract_v2(p2)["contract_id"] != first)

    for key, value in (("data_link", "data-elsewhere"), ("site_dir", "site-elsewhere"),
                       ("publication_site", "somewhere"), ("production_data_key", "verbatim.x.productionData"),
                       ("description", "renamed")):
        check(f"changing {key} does not change it", not moved(lambda p, k=key, v=value: p.update({k: v})))
    p3 = copy.deepcopy(prof)
    p3["skill_dir"] = str(tmp / "no-such-skill")
    try:
        GC.contract_v2(p3)
        refused = False
    except RuntimeError as exc:
        refused = "does not exist" in str(exc)
    check("a missing PROMPT.md is refused, not hashed as absent", refused)


def test_render(tmp: Path) -> None:
    print("\n[RENDER]")
    import grading_contract as GC
    prof = fixture_profile(fixture_skill(tmp / "render"))
    values = GC.prompt_values(REC, "fixture rubric\n", "{}", prof)
    blinded, opened = GC.render_prompt(TEMPLATE, "blinded", values), GC.render_prompt(TEMPLATE, "open", values)
    check("blinded keeps its branch and drops the open one",
          "withheld" in blinded and "Pat Undit" not in blinded and "<<<" not in blinded)
    check("open keeps its branch and drops the blinded one",
          "Speaker: Pat Undit" in opened and "withheld" not in opened and "<<<" not in opened)
    strip = lambda s, branch: s.replace(branch, "")
    check("the two modes differ only in the identity branch",
          strip(blinded, "IDENTITY: withheld. Do not try to work out who is speaking.\n")
          == strip(opened, "IDENTITY: Speaker: Pat Undit\n"))
    check("metadata is identical in both modes", values["metadata"] in blinded and values["metadata"] in opened)
    check("a transcript containing {{rubric}} is inserted as text",
          "we disagree about this {{rubric}} point" in blinded)
    try:
        GC.render_prompt(TEMPLATE + "{{role}}", "blinded", values)
        refused = False
    except RuntimeError as exc:
        refused = "role" in str(exc)
    check("an unknown placeholder is refused, naming it", refused)


def load_grade():
    spec = importlib.util.spec_from_file_location("grade_p2", REPO / "scripts" / "grade.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def canned_grade(tid: str) -> dict:
    dims = {}
    subs = []
    import grading_contract as GC  # noqa: F401
    scoring = json.loads((REPO / "profiles/pundits.json").read_text())["scoring"]
    for d in scoring["dimensions"]:
        dims[d["key"]] = {"dimension_status": "supported", "score": 60,
                          "reasoning": "word " * 25,
                          "evidence": [{"quote": "a short quote", "timestamp": "unmarked", "speaker": "subject",
                                        "why_it_matters": "x"}] * 2,
                          "counterevidence": "none found"}
        subs += [{"code": c, "score": 3, "justification": "x"} for c in d["subcriteria"]]
    return {"transcript_id": tid, "subcriteria": subs, "dimensions": dims, "overall": 60.0}


def test_cache(tmp: Path) -> None:
    print("\n[CACHE]")
    import grading_contract as GC
    try:
        G = load_grade()
    except Exception as exc:
        check("grade.py loads", False, repr(exc))
        return
    if not hasattr(G, "v2_identity"):
        check("grade.py exposes v2_identity for contract v2 jobs", False)
        return
    sd = fixture_skill(tmp / "cache")
    prof = fixture_profile(sd)
    contract = GC.contract_v2(prof)
    src = tmp / "cache-in" / "s1.json"
    src.parent.mkdir(parents=True)
    src.write_text(json.dumps(REC))
    out = tmp / "cache-out"
    calls = []

    def stub(prompt, *a, **k):
        calls.append(prompt)
        return json.dumps(canned_grade("pundit-p/s1")), {"judge_model": "claude-fable-5-1",
                                                          "requested_model": "claude-fable-5-1"}

    G.call_fable = stub

    def job(**over):
        j = {"rec": dict(REC), "judge": "fable", "mode": "blinded", "run": 0, "force": False,
             "contract_version": 2, "profile": prof, "contract": contract,
             "rubric": (sd / "RUBRIC.md").read_text(), "schema": (sd / "judge_output.schema.json").read_text(),
             "template": (sd / "PROMPT.md").read_text(),
             "input_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
             "requested_model": "claude-fable-5-1", "provenance_id": "fixtureprov",
             "config_dir": "__DEFAULT__", "timeout": 5, "fable_bin": "claude", "workdir": str(tmp / "wd"),
             "dest": str(out / "fable/pundit-p/s1__fable__blinded__r0.json"),
             "raw_dest": str(out / "_raw/fable/pundit-p/s1__fable__blinded__r0.txt"),
             "obsolete_root": str(out / "_obsolete"),
             # Every contract v2 job carries its judge harness (P3); the stub ignores it.
             "harness": G.v2_harness(prof, "fable", tmp / "sandboxed-container")}
        j.update(over)
        return j

    r = G.grade_one(job())
    dest = Path(job()["dest"])
    rec = json.loads(dest.read_text()) if dest.exists() else {}
    check("a fresh v2 grade is written", r.get("status") == "ok" and dest.exists(), str(r))
    check("it carries the full identity block", rec.get("identity") == G.v2_identity(job()), str(rec.get("identity")))
    check("it records the requested and served model, and whether served was verified",
          rec.get("requested_model") == "claude-fable-5-1" and rec.get("served_model") == "claude-fable-5-1"
          and rec.get("served_model_verified") is True, str({k: rec.get(k) for k in
                                                            ("requested_model", "served_model", "served_model_verified")}))
    check("it references its run's provenance", rec.get("provenance_id") == "fixtureprov")
    n = len(calls)
    r = G.grade_one(job())
    check("an identical job reuses it without calling the judge", r.get("status") == "cached" and len(calls) == n, str(r))

    # A stored record that FAILED validation must not count as a cache hit.
    # Found live 2026-09-16: 6 Gemini cells whose run-0 records broke the 25-word
    # quote cap came back `CACHED` when scheduled again, because the cache asks
    # only whether the IDENTITY matches. Identity says "this is the same
    # question"; it says nothing about whether the answer is usable. Left alone,
    # those cells can never be repaired without --force and a two-judge panel
    # quietly keeps a hole in it.
    invalid = json.loads(dest.read_text())
    invalid["validation_errors"] = ["d1_steelmanning quote exceeds 25 words"]
    dest.write_text(json.dumps(invalid))
    n = len(calls)
    r = G.grade_one(job())
    check("a stored grade that failed validation is not reused as a cache hit",
          r.get("status") != "cached" and len(calls) > n, str(r))
    G.grade_one(job())  # restore a valid record for the checks below
    n = len(calls)
    r = G.grade_one(job())
    check("a valid stored grade is still reused", r.get("status") == "cached" and len(calls) == n, str(r))

    before = dest.read_bytes()
    for field, over in (("input_sha256", {"input_sha256": "0" * 64}),
                        ("mode", {"mode": "open"}),
                        ("requested_model", {"requested_model": "claude-other"}),
                        ("run", {"run": 1}),
                        ("prompt_sha256", {"template": TEMPLATE + "\nextra line\n"})):
        j = job(**over)
        j["dest"] = str(dest)
        r = G.grade_one(j)
        check(f"a stored grade with a different {field} is refused, naming the field",
              r.get("status") == "stale_cache" and field in (r.get("detail") or ""), str(r))
    stale_contract = copy.deepcopy(contract)
    stale_contract["contract_id"] = "0" * 16
    r = G.grade_one(job(contract=stale_contract))
    check("a stored grade under another contract is refused, naming contract_id",
          r.get("status") == "stale_cache" and "contract_id" in (r.get("detail") or ""), str(r))
    check("no refused lookup called the judge", len(calls) == n)
    check("and the stored grade is byte-identical afterwards", dest.read_bytes() == before)

    r = G.grade_one(job(contract=stale_contract, force=True))
    obsolete = list(Path(job()["obsolete_root"]).rglob("*.json"))
    new = json.loads(dest.read_text())
    check("--force moves the stale grade aside first", len(obsolete) == 1 and obsolete[0].read_bytes() == before,
          str(obsolete))
    check("and writes a replacement stamped with the new identity",
          new.get("identity") == G.v2_identity(job(contract=stale_contract)) and len(calls) == n + 1, str(r))

    legacy = {"rec": dict(REC), "judge": "fable", "mode": "blinded", "run": 0, "force": False,
              "dest": str(dest), "raw_dest": job()["raw_dest"]}
    r = G.grade_one(legacy)
    check("a leaders (v1) job still reuses any existing file, as before", r.get("status") == "cached", str(r))


def data_checkout(path: Path, slug: str) -> None:
    path.mkdir(parents=True)
    for args in (("init", "-q", "-b", "main"), ("config", "user.email", "446441+tonygwu@users.noreply.github.com"),
                 ("config", "user.name", "Fixture"),
                 ("config", "remote.origin.url", "git@github.com:tonygwu/verbatim-pundits-data.git")):
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)
    (path / ".study").write_text("pundits\n")
    (path / "roster").mkdir()
    (path / "roster/final.json").write_text(json.dumps({"roster": [
        {"slug": slug, "name": "Pat Undit", "company": "Show", "role": "host", "sector": "politics"}]}))


def write_grade(root: Path, contract_id: str, study: str | None, slug: str, sid: str) -> None:
    ident = {"study_id": study, "contract_id": contract_id, "prompt_sha256": "p", "input_sha256": "i",
             "mode": "blinded", "judge": "fable", "requested_model": "claude-fable-5-1", "run": 0}
    rec = {"transcript_id": f"{slug}/{sid}", "leader_slug": slug, "source_id": sid, "judge": "fable",
           "mode": "blinded", "run": 0, "grading_contract": {"contract_id": contract_id},
           "identity": ident if study else None, "validation_errors": [], "grade": canned_grade(f"{slug}/{sid}")}
    p = root / "grades/fable" / slug / f"{sid}__fable__blinded__r0.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec))


def test_aggregate(tmp: Path) -> None:
    print("\n[AGGREGATE] a real aggregate.py run under a fixture contract")
    import grading_contract as GC
    sd = fixture_skill(tmp / "agg")
    prof = fixture_profile(sd)
    profiles = tmp / "profiles"
    profiles.mkdir()
    (profiles / "pundits.json").write_text(json.dumps(prof))
    shutil.copy2(REPO / "profiles/leaders.json", profiles / "leaders.json")
    current = GC.contract_v2(prof)["contract_id"]

    def run_case(name: str, grades: list[tuple]) -> subprocess.CompletedProcess:
        root = tmp / f"agg-{name}"
        data_checkout(root, "pundit-p")
        for g in grades:
            write_grade(root, *g)
        env = {k: v for k, v in os.environ.items() if k != "STUDY"}
        env["VI_PROFILES_DIR"] = str(profiles)
        return subprocess.run([PY, REPO / "scripts/aggregate.py", "--study", "pundits",
                               "--grades", root / "grades", "--roster", root / "roster/final.json",
                               "--out", root / "results.json"], env=env, capture_output=True, text=True)

    r = run_case("obsolete", [("0" * 16, "pundits", "pundit-p", f"s{i}") for i in range(3)])
    check("an all-obsolete corpus is refused", r.returncode != 0 and "REFUSING TO AGGREGATE" in r.stderr
          and "contract" in r.stderr, r.stderr[-400:])
    r = run_case("leaders-grade", [(current, "pundits", "pundit-p", "s1"), (current, None, "pundit-p", "s2")])
    check("a grade with no pundits identity is refused as another study",
          r.returncode != 0 and "REFUSING TO AGGREGATE" in r.stderr and "study" in r.stderr, r.stderr[-400:])
    r = run_case("roster", [(current, "pundits", "someone-else", "s1")])
    check("a slug not on the roster is refused",
          r.returncode != 0 and "REFUSING TO AGGREGATE" in r.stderr and "roster" in r.stderr, r.stderr[-400:])
    r = run_case("current", [(current, "pundits", "pundit-p", f"s{i}") for i in range(3)])
    check("a current corpus is not refused on contract grounds", "REFUSING TO AGGREGATE" not in r.stderr,
          r.stderr[-400:])


def main() -> int:
    print("pundits grading contract v2")
    with tempfile.TemporaryDirectory(prefix="contract-v2-") as td:
        tmp = Path(td).resolve()
        try:
            import grading_contract  # noqa: F401
        except Exception as exc:
            check("grading_contract is importable", False, repr(exc))
        else:
            test_contract_scope(tmp)
            test_render(tmp)
            test_cache(tmp)
            test_aggregate(tmp)
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
