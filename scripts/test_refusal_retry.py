#!/usr/bin/env python3
"""Guards for the refusal retry policy, added 2026-09-07.

MEASURED. Astra refused 11 blinded transcripts on content grounds, concentrated
on the leaders who discuss politics: 6 of Alex Karp's and 3 of Elon Musk's. A
controlled re-run of three of them found the refusals are NOT deterministic.
gpt-6-astra refused elon-musk/lex-fridman-jn3kpf and
tim-cook/the-uptake-by-bridgemake-fwv5jc in production and graded both on the
re-run, same transcript and prompt. Only alex-karp/the-free-press-qdqhf7 refused
twice. So a retry recovers most of them.

There is deliberately no fallback to a second model. Such grades could not be
calibrated: there would only ever be a handful, far below MIN_CALIBRATION_N, so
they would enter the leaderboard unrescaled and about six points high, and only
on the leaders where refusals concentrate. Calibration is still keyed by the
model that answered, because a judge whose model is BUMPED mid-corpus is the
same hazard arriving a different way.

  .venv/bin/python scripts/test_refusal_retry.py
"""
from __future__ import annotations
import importlib.util, inspect, json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []

def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if detail and not ok:
        print(f"          {detail}")

def load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_m", REPO / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

REFUSAL = {"assessment_limit": "I can't assign the requested scores because they would "
                               "evaluate political and policy reasoning."}
def good_grade():
    return {"schema_version": "1.0", "overall": 55.0,
            "dimensions": {d: {"score": 55} for d in
                           ("d1_clarity", "d2_insight", "d3_technical_depth")}}


def test_retries_same_model():
    print("\n[1] a refusal is retried on the same model")
    g = load("grade")
    check("the attempt budget is a named constant, not a magic number",
          isinstance(getattr(g, "REFUSAL_ATTEMPTS", None), int) and g.REFUSAL_ATTEMPTS >= 2,
          f"REFUSAL_ATTEMPTS={getattr(g,'REFUSAL_ATTEMPTS',None)}")
    calls = []
    def fake(model):
        calls.append(model)
        return (REFUSAL, {}) if len(calls) == 1 else (good_grade(), {})
    obj, tel, info = g.grade_with_refusal_policy(fake, primary="gpt-6-astra")
    check("it called the model twice", calls == ["gpt-6-astra"] * 2, f"{calls}")
    check("it returns the grade, not the refusal", obj.get("overall") == 55.0, f"{obj}")
    check("it records how many attempts it took", info["attempts"] == 2, f"{info}")
    check("it records which model answered", info["served_model"] == "gpt-6-astra", f"{info}")
    check("and that it is no longer refused", info["refused"] is False, f"{info}")


def test_there_is_no_fallback_model():
    print("\n[2] there is no fallback to another model, deliberately")
    g = load("grade")
    sig = inspect.signature(g.grade_with_refusal_policy)
    check("the policy takes no fallback model", "fallback" not in sig.parameters, f"{sig}")
    src = (REPO / "scripts" / "grade.py").read_text()
    check("no second judge model id is hardcoded anywhere",
          "gpt-5.6-sol" not in src, "a second judge model is still wired in")
    check("there is no --astra-fallback flag", "--astra-fallback" not in src)
    check("the reason is written down beside the constant, so it is not silently re-added",
          "cannot be calibrated" in src, "a future reader will re-add it without knowing why")


def test_exhausted_retries_stay_a_refusal():
    print("\n[3] when every retry refuses it stays a refusal rather than being forced")
    g = load("grade")
    calls = []
    def fake(model):
        calls.append(model); return (REFUSAL, {})
    obj, tel, info = g.grade_with_refusal_policy(fake, primary="gpt-6-astra")
    check(f"the model was tried exactly REFUSAL_ATTEMPTS ({g.REFUSAL_ATTEMPTS}) times",
          len(calls) == g.REFUSAL_ATTEMPTS, f"{calls}")
    check("no other model was ever called", set(calls) == {"gpt-6-astra"}, f"{calls}")
    check("the refusal is returned honestly", g.looks_like_refusal(obj) is not None, f"{obj}")
    check("and it is recorded as still refused", info["refused"] is True, f"{info}")


def test_first_pass_costs_one_call():
    print("\n[4] a transcript that grades first time costs exactly one call")
    g = load("grade")
    calls = []
    def fake(model):
        calls.append(model); return (good_grade(), {})
    obj, tel, info = g.grade_with_refusal_policy(fake, primary="gpt-6-astra")
    check("one call, no speculative retry", calls == ["gpt-6-astra"], f"{calls}")
    check("attempts is 1", info["attempts"] == 1, f"{info}")


# ---------------------------------------------------------------------------
# 5. Calibration is keyed by the model that answered.
#
# There is no fallback now, but the hazard it exposed is real and arrives
# another way: a judge's model gets BUMPED. calibrate() maps a judge's score
# distribution onto the pooled one, so pooling two different models under one
# judge name rescales both by statistics belonging to neither. The two models
# measured here differed by 3.65 points on the one transcript both graded.
# ---------------------------------------------------------------------------
def test_calibration_separates_the_models():
    print("\n[5] two models under one judge name are calibrated separately")
    a = load("aggregate")
    def gr(model, score, sid):
        return {"leader_slug": "x", "source_id": sid, "judge": "astra", "mode": "blinded",
                "telemetry": {"served_model": model},
                "grade": {"dimensions": {d: {"score": score} for d in a.DIMS},
                          "coverage": 1.0, "overall": float(score)}}
    grades = [gr("gpt-6-astra", 60 + (i % 7), f"t{i}") for i in range(60)]
    grades += [gr("gpt-6-astra-v2", 90, f"n{i}") for i in range(3)]
    params = a.calibrate(grades)
    check("calibration is keyed by the model, not only the judge name",
          any("gpt-6-astra-v2" in str(k) for k in params),
          f"keys={sorted(str(k) for k in list(params)[:4])}")
    check("the three new-model grades do not move the old model's mean",
          abs(params[("astra", "gpt-6-astra", "blinded", a.DIMS[0])]["judge_mean"] - 63.0) < 1.5,
          f"{params.get(('astra','gpt-6-astra','blinded',a.DIMS[0]))}")
    check("a model with too few grades is not rescaled on its own thin statistics",
          params[("astra", "gpt-6-astra-v2", "blinded", a.DIMS[0])]["rescaled"] is False,
          f"{params.get(('astra','gpt-6-astra-v2','blinded',a.DIMS[0]))}")
    check("MIN_CALIBRATION_N is a named constant",
          isinstance(getattr(a, "MIN_CALIBRATION_N", None), int),
          f"{getattr(a,'MIN_CALIBRATION_N',None)}")


def test_a_second_model_is_reported_loudly():
    print("\n[6] a judge serving two models is reported, not silently averaged")
    a = load("aggregate")
    src = (REPO / "scripts" / "aggregate.py").read_text()
    check("aggregate.py reports the models each judge served",
          '"judge_models"' in src, "diagnostics do not say which models answered")
    check("and warns when a judge served more than one",
          "served more than one model" in src,
          "a mid-corpus model bump would pass unremarked")


def test_old_grades_still_work():
    print("\n[7] grades written before served_model existed still calibrate")
    a = load("aggregate")
    old = [{"leader_slug": "x", "source_id": f"t{i}", "judge": "fable", "mode": "blinded",
            "grade": {"dimensions": {d: {"score": 50 + (i % 9)} for d in a.DIMS},
                      "coverage": 1.0, "overall": 50.0}} for i in range(60)]
    params = a.calibrate(old)
    check("a record with no telemetry does not crash the fit", bool(params))
    check("it is filed under the judge's default model", any(k[0] == "fable" for k in params))
    v = a.apply_calibration(55.0, [k for k in params if k[3] == a.DIMS[0]][0], params)
    check("and it still calibrates to a sane number", 1.0 <= v <= 100.0, f"{v}")


def test_live_path_uses_the_policy():
    print("\n[8] the production grading path goes through the policy")
    g = load("grade")
    src = (REPO / "scripts" / "grade.py").read_text()
    sig = inspect.signature(g.call_astra)
    check("call_astra takes the model as an argument", "model" in sig.parameters, f"{sig}")
    check("its default is the primary model", sig.parameters["model"].default == "gpt-6-astra",
          f"{sig.parameters.get('model')}")
    astra_branch = src.split('if job["judge"] == "fable"')[1][:1500]
    check("the astra branch calls grade_with_refusal_policy",
          "grade_with_refusal_policy(" in astra_branch,
          "the live path still calls call_astra once and takes the refusal")
    check("the served model is written onto the grade record", '"served_model"' in src)
    check("the attempt count is written onto the grade record", '"refusal_attempts"' in src)
    check("the primary model is configurable from the command line", "--astra-model" in src)


def test_every_name_in_the_live_path_resolves():
    print("\n[9] grade.py has no dangling names after the edits")
    import ast, builtins
    src = (REPO / "scripts" / "grade.py").read_text()
    tree = ast.parse(src)
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    defined |= {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name)}
    defined |= {a.asname or a.name.split(".")[0]
                for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in n.names}
    # Parameters and local bindings count as defined: a callable passed in as an
    # argument is not a dangling name.
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            aa = n.args
            defined |= {p.arg for p in aa.args + aa.posonlyargs + aa.kwonlyargs}
            if aa.vararg: defined.add(aa.vararg.arg)
            if aa.kwarg: defined.add(aa.kwarg.arg)
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    missing = sorted(called - defined - set(dir(builtins)))
    # A helper called but never defined is exactly the bug this caught: an edit
    # sliced out _policy_fields while leaving both call sites in place, which
    # only shows up as a NameError once a real grading job runs.
    check("every function grade.py calls by bare name is defined or imported",
          not missing, f"undefined: {missing}")


def main() -> int:
    print("refusal retry guards")
    test_retries_same_model()
    test_there_is_no_fallback_model()
    test_exhausted_retries_stay_a_refusal()
    test_first_pass_costs_one_call()
    test_calibration_separates_the_models()
    test_a_second_model_is_reported_loudly()
    test_old_grades_still_work()
    test_live_path_uses_the_policy()
    test_every_name_in_the_live_path_resolves()
    print(f"\n{len(PASS)}/{len(PASS)+len(FAIL)} passed")
    if FAIL: print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
