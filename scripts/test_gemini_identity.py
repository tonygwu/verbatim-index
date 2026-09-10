#!/usr/bin/env python3
"""Two Antigravity profiles that serve one account must be reported, not assumed apart.

FOUND 2026-09-10: all 567 Gemini grades in the corpus were served by
gptwufamily@gmail.com although two profile HOMEs were in rotation. `agy` keeps
its credential in the macOS Keychain under one fixed service and account, so
the HOMEs share it and the last refresh wins. Pure checks, no quota.

  .venv/bin/python scripts/test_gemini_identity.py
"""
from __future__ import annotations
import importlib.util, json, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []
def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))

spec = importlib.util.spec_from_file_location("g", REPO / "scripts" / "grade.py")
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)

def grade_file(td, name, home, ident):
    p = Path(td) / name
    p.write_text(json.dumps({"telemetry": {"profile_home": home, "profile_identity": ident}}))
    return {"judge": "gemini", "status": "ok", "path": str(p)}

with tempfile.TemporaryDirectory() as td:
    same = [grade_file(td, "a.json", "/h/a", "x@gmail.com"), grade_file(td, "b.json", "/h/b", "x@gmail.com"),
            grade_file(td, "c.json", "/h/a", "x@gmail.com")]
    r = g.gemini_identity_report(same)
    check("two profiles, one identity is flagged", r["one_account_behind_all_profiles"] is True, str(r))
    check("counts are per profile", r["profiles"] == {"/h/a": {"x@gmail.com": 2}, "/h/b": {"x@gmail.com": 1}}, str(r))
    two = [grade_file(td, "d.json", "/h/a", "x@gmail.com"), grade_file(td, "e.json", "/h/b", "y@gmail.com")]
    r2 = g.gemini_identity_report(two)
    check("two profiles, two identities is not flagged", r2["one_account_behind_all_profiles"] is False, str(r2))
    check("distinct identities are listed", r2["distinct_identities"] == ["x@gmail.com", "y@gmail.com"])
    one = [grade_file(td, "f.json", "/h/a", "x@gmail.com")]
    check("a single profile is never flagged", g.gemini_identity_report(one)["one_account_behind_all_profiles"] is False)
    other = [{"judge": "fable", "status": "ok", "path": str(Path(td) / "a.json")}, {"judge": "gemini", "status": "failed"}]
    check("non-gemini and failed results are ignored", g.gemini_identity_report(other)["profiles"] == {})
    check("a missing grade file is skipped, not fatal",
          g.gemini_identity_report([{"judge": "gemini", "status": "ok", "path": str(Path(td) / "nope.json")}])["profiles"] == {})
src = (REPO / "scripts" / "grade.py").read_text()
check("the run summary carries gemini_identities", '"gemini_identities": gemini_ids' in src)
check("a one-account rotation is warned about", "every one of them served" in src)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL: print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
