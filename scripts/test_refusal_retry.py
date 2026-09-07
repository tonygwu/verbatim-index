#!/usr/bin/env python3
"""Guards for the refusal retry-then-fallback policy, added 2026-09-07.

MEASURED. Astra refused 11 blinded transcripts on content grounds, concentrated
on the leaders who discuss politics: 6 of Alex Karp's and 3 of Elon Musk's. A
controlled re-run of three of them found the refusals are NOT deterministic.
gpt-6-astra refused elon-musk/lex-fridman-jn3kpf and
tim-cook/the-uptake-by-bridgemake-fwv5jc in production and graded both on the
re-run, same transcript, same prompt. Only alex-karp/the-free-press-qdqhf7
refused twice.

So this is sampling variance on a borderline judgement, not a hard content
block, and a retry recovers most of it. gpt-5.6-sol graded the one that refused
twice, at 49.1 with a valid schema.

Policy: retry the same model, then fall back to another model only when it keeps
refusing. The fallback is the part that needs care, because the pipeline
calibrates per judge and a judge that is sometimes one model and sometimes
another has no stable distribution to calibrate.

  .venv/bin/python scripts/test_refusal_retry.py
"""
from __future__ import annotations
import importlib.util, json, sys, tempfile
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


# ---------------------------------------------------------------------------
# 1. A refusal is retried on the SAME model before anything else is tried.
# ---------------------------------------------------------------------------
def test_retries_same_model_first():
    print("\n[1] a refusal is retried on the same model before falling back")
    g = load("grade")
    check("the attempt budget is a named constant, not a magic number",
          isinstance(getattr(g, "REFUSAL_ATTEMPTS", None), int) and g.REFUSAL_ATTEMPTS >= 2,
          f"REFUSAL_ATTEMPTS={getattr(g,'REFUSAL_ATTEMPTS',None)}")

    calls = []
    def fake(model):
        calls.append(model)
        # refuses once, then grades: the common case the measurement found
        return (REFUSAL, {}) if len(calls) == 1 else (good_grade(), {})
    obj, tel, info = g.grade_with_refusal_policy(fake, primary="gpt-6-astra",
                                                 fallback="gpt-5.6-sol")
    check("it called the primary model twice", calls == ["gpt-6-astra", "gpt-6-astra"], f"{calls}")
    check("it never reached the fallback", "gpt-5.6-sol" not in calls, f"{calls}")
    check("it returns the grade, not the refusal", obj.get("overall") == 55.0, f"{obj}")
    check("it records how many attempts it took", info["attempts"] == 2, f"{info}")
    check("it records which model actually answered", info["served_model"] == "gpt-6-astra", f"{info}")
    check("it records that no fallback was used", info["fallback_used"] is False, f"{info}")


def test_falls_back_only_after_the_budget():
    print("\n[2] the fallback runs only after the primary has refused its full budget")
    g = load("grade")
    calls = []
    def fake(model):
        calls.append(model)
        return (REFUSAL, {}) if model == "gpt-6-astra" else (good_grade(), {})
    obj, tel, info = g.grade_with_refusal_policy(fake, primary="gpt-6-astra",
                                                 fallback="gpt-5.6-sol")
    check(f"the primary was tried exactly REFUSAL_ATTEMPTS ({g.REFUSAL_ATTEMPTS}) times",
          calls.count("gpt-6-astra") == g.REFUSAL_ATTEMPTS, f"{calls}")
    check("the fallback was tried once, not repeatedly",
          calls.count("gpt-5.6-sol") == 1, f"{calls}")
    check("the fallback's grade is returned", obj.get("overall") == 55.0, f"{obj}")
    check("the served model is the fallback", info["served_model"] == "gpt-5.6-sol", f"{info}")
    check("fallback_used is flagged so calibration can see it", info["fallback_used"] is True, f"{info}")


def test_both_refuse_is_still_a_refusal():
    print("\n[3] if both models refuse it stays a refusal rather than being forced")
    g = load("grade")
    calls = []
    def fake(model):
        calls.append(model); return (REFUSAL, {})
    obj, tel, info = g.grade_with_refusal_policy(fake, primary="gpt-6-astra",
                                                 fallback="gpt-5.6-sol")
    check("every attempt was spent", len(calls) == g.REFUSAL_ATTEMPTS + 1, f"{calls}")
    check("the refusal is returned honestly", g.looks_like_refusal(obj) is not None, f"{obj}")
    check("and it is recorded as still refused", info["refused"] is True, f"{info}")


def test_no_fallback_configured():
    print("\n[4] with no fallback configured it retries and then gives up")
    g = load("grade")
    calls = []
    def fake(model):
        calls.append(model); return (REFUSAL, {})
    obj, tel, info = g.grade_with_refusal_policy(fake, primary="gpt-6-astra", fallback=None)
    check("only the primary was ever called", set(calls) == {"gpt-6-astra"}, f"{calls}")
    check("it did not invent a fallback model", info["fallback_used"] is False, f"{info}")
    check("it is still a refusal", info["refused"] is True, f"{info}")


def test_a_first_pass_grade_costs_one_call():
    print("\n[5] a transcript that grades first time costs exactly one call")
    g = load("grade")
    calls = []
    def fake(model):
        calls.append(model); return (good_grade(), {})
    obj, tel, info = g.grade_with_refusal_policy(fake, primary="gpt-6-astra",
                                                 fallback="gpt-5.6-sol")
    check("one call, no speculative retry", calls == ["gpt-6-astra"], f"{calls}")
    check("attempts is 1", info["attempts"] == 1, f"{info}")


# ---------------------------------------------------------------------------
# 6. The correctness trap. Calibration is per judge; the fallback is a
#    DIFFERENT MODEL under the same judge name.
#
# calibrate() maps a judge's score distribution onto the pooled one. If a
# handful of gpt-5.6-sol grades are filed as "astra" and pooled into astra's
# distribution, they are rescaled by statistics that are not theirs. On the one
# transcript where both models graded, sol scored 68.35 against astra's 64.7, so
# the distributions are not interchangeable.
# ---------------------------------------------------------------------------
def test_calibration_separates_the_models():
    print("\n[6] a fallback grade is not calibrated as if the primary produced it")
    a = load("aggregate")
    def gr(judge, model, score, sid):
        return {"leader_slug": "x", "source_id": sid, "judge": judge, "mode": "blinded",
                "telemetry": {"served_model": model},
                "grade": {"dimensions": {d: {"score": score} for d in a.DIMS},
                          "coverage": 1.0, "overall": float(score)}}
    grades = [gr("astra", "gpt-6-astra", 60 + (i % 7), f"t{i}") for i in range(60)]
    grades += [gr("astra", "gpt-5.6-sol", 90, f"f{i}") for i in range(3)]
    params = a.calibrate(grades)
    keys = {k[0] for k in params}
    check("calibration is keyed by the model that answered, not only the judge name",
          any("gpt-5.6-sol" in str(k) for k in params),
          f"keys={sorted(str(k) for k in list(params)[:6])}")
    check("the three fallback grades do not move the primary model's mean",
          abs(params[("astra", "gpt-6-astra", "blinded", a.DIMS[0])]["judge_mean"] - 63.0) < 1.5,
          f"{params.get(('astra','gpt-6-astra','blinded',a.DIMS[0]))}")
    check("a model with too few grades is not rescaled on its own thin statistics",
          params[("astra", "gpt-5.6-sol", "blinded", a.DIMS[0])]["rescaled"] is False,
          f"{params.get(('astra','gpt-5.6-sol','blinded',a.DIMS[0]))}")
    check("MIN_CALIBRATION_N is a named constant",
          isinstance(getattr(a, "MIN_CALIBRATION_N", None), int), f"{getattr(a,'MIN_CALIBRATION_N',None)}")
    raw = 90.0
    out = a.apply_calibration(raw, ("astra", "gpt-5.6-sol", "blinded", a.DIMS[0]), params)
    check("an unrescaled grade passes through untouched rather than being guessed at",
          out == raw, f"{out}")


def test_old_grades_still_work():
    print("\n[7] grades written before served_model existed still calibrate")
    a = load("aggregate")
    old = [{"leader_slug": "x", "source_id": f"t{i}", "judge": "fable", "mode": "blinded",
            "grade": {"dimensions": {d: {"score": 50 + (i % 9)} for d in a.DIMS},
                      "coverage": 1.0, "overall": 50.0}} for i in range(60)]
    params = a.calibrate(old)
    check("a record with no telemetry does not crash the fit", bool(params), "calibrate returned nothing")
    check("it is filed under the judge's default model",
          any(k[0] == "fable" for k in params), f"{sorted(str(k) for k in list(params)[:4])}")
    v = a.apply_calibration(55.0, [k for k in params if k[3] == a.DIMS[0]][0], params)
    check("and it still calibrates to a sane number", 1.0 <= v <= 100.0, f"{v}")


def test_the_live_path_uses_the_policy():
    print("\n[8] the production grading path actually goes through the policy")
    src = (REPO / "scripts" / "grade.py").read_text()
    # Check the real signature, not a source string: the first version of this
    # matched a one-line "def call_astra(...)" and broke the moment the line
    # wrapped, which says nothing about the behaviour.
    import inspect
    g = load("grade")
    sig = inspect.signature(g.call_astra)
    check("call_astra takes the model as an argument rather than hardcoding it",
          "model" in sig.parameters, f"signature is {sig}")
    check("its default is the primary model, so existing callers are unchanged",
          sig.parameters["model"].default == "gpt-6-astra", f"{sig.parameters.get('model')}")
    check("the astra branch calls grade_with_refusal_policy",
          "grade_with_refusal_policy(" in src.split("if job[\"judge\"] == \"fable\"")[1][:1200],
          "the live path still calls call_astra once and takes the refusal")
    check("the served model is written onto the grade record",
          '"served_model"' in src, "calibration cannot tell the models apart")
    check("the attempt count is written onto the grade record", '"refusal_attempts"' in src)
    check("the fallback flag is written onto the grade record", '"fallback_used"' in src)
    check("the fallback model is configurable from the command line",
          "--astra-fallback" in src, "a model id should not be hardcoded into the run")


def main() -> int:
    print("refusal retry-and-fallback guards")
    test_retries_same_model_first()
    test_falls_back_only_after_the_budget()
    test_both_refuse_is_still_a_refusal()
    test_no_fallback_configured()
    test_a_first_pass_grade_costs_one_call()
    test_calibration_separates_the_models()
    test_old_grades_still_work()
    test_the_live_path_uses_the_policy()
    print(f"\n{len(PASS)}/{len(PASS)+len(FAIL)} passed")
    if FAIL: print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
