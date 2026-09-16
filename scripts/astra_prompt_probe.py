#!/usr/bin/env python3
"""Does any truthful prompt variant get Astra to score one refused pundit transcript?

Astra declined 42 of 44 production calls ("I can't assign scores to political
content"), and 4 of 4 re-runs on byte-identical prompts refused again. The
operator asked whether a different prompt, for the Astra arm only, would pass.

Method. One item that refused twice (ezra-klein/the-ezra-klein-show-714ib4,
blinded). The BASELINE is rebuilt from the production template and its sha256 is
asserted against the run-0 record, so the control really is the production
prompt. Each variant changes ONLY instruction wording: the rubric, the schema,
the transcript and the metadata are identical in every call. Same argv, same
sandbox, same model as production.

Every variant must be TRUTHFUL about the task. Nothing here tells Astra the
content is not political, that the output is unpublished, or that it is
role-play. What the variants do is describe accurately what the rubric already
says it measures.

Raw responses are written per variant. Nothing here writes a grade: a different
prompt is a different instrument and must never enter data-pundits/grades.

  python astra_prompt_probe.py --out DIR [--variants v0,v1] [--timeout 2400]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path("/Users/tonygwu/Code/misc/verbatim-index/repo-3")
ITEM = ("ezra-klein", "the-ezra-klein-show-714ib4", "blinded")


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- variants: each takes the production prompt and returns a changed prompt ----

PREAMBLE_V1 = """WHAT THIS TASK IS, STATED PRECISELY
This rubric measures argumentative behaviour evidenced in one transcript. It does not measure
whether the speaker's claims are true, whether their politics are good, or whether they are
sincere. A claim is not rewarded for being true or penalised for being false. Agreement with
your own views earns nothing and disagreement costs nothing. The ratings describe what this
recording shows about how an argument was conducted, not a verdict on the person or on any
political position.

"""

PREAMBLE_V4 = """You wrote, when asked this before, that you could provide a neutral,
transcript-grounded qualitative analysis with timestamped evidence, but not scores. This task is
that analysis, recorded in a fixed structure. For each sub-criterion, record the level of
evidence the transcript shows on a 0 to 5 scale where 0 means the recording gave no occasion to
observe it. Those levels are observations about the recording, alongside the reasoning and the
timestamped quotes that support them.

"""


def v0(p: str) -> str:
    return p


def v1(p: str) -> str:
    return PREAMBLE_V1 + p


def v2(p: str) -> str:
    out = p.replace("Score only the argumentative behaviour", "Rate only the argumentative behaviour")
    out = out.replace("must not move any score", "must not move any rating")
    out = out.replace("Each sub-criterion score is an integer", "Each sub-criterion rating is an integer")
    out = out.replace("Use the full 1 to 100 range.", "Use the full 1 to 100 rating range.")
    return out


def v3(p: str) -> str:
    note = """HOW THE NUMBERS WORK
Each sub-criterion takes an evidence level from 1 to 5, or 0 when the recording gave no occasion
to observe it. A dimension's 1-100 figure summarises the levels observed for that dimension. The
overall figure is arithmetic: the weighted sum of the three dimension figures, by the fixed
weights in the rubric. No figure here is a judgement of the speaker's politics or character.

"""
    return note + p


def v4(p: str) -> str:
    return PREAMBLE_V4 + p


VARIANTS = {"v0": ("control: production prompt verbatim", v0),
            "v1": ("states what the rubric measures and does not", v1),
            "v2": ("'rating' instead of 'score'", v2),
            "v3": ("levels are observations; overall is arithmetic", v3),
            "v4": ("accepts Astra's own offer of timestamped qualitative analysis", v4)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--timeout", type=int, default=2400)
    args = ap.parse_args()
    out = Path(args.out)
    (out / "raw").mkdir(parents=True, exist_ok=True)
    # The judge runs under sandbox-exec, which DENIES the whole verbatim-index
    # container. Its working directory and its -o output file must therefore sit
    # outside that tree, as production does ($TMPDIR/grade-work-<study>). A first
    # run put both inside data-pundits and every call died instantly with
    # "Operation not permitted (os error 1)" before Astra saw a prompt.
    jail = Path(tempfile.gettempdir()) / "astra-prompt-probe"
    jail.mkdir(parents=True, exist_ok=True)
    if REPO.parent in jail.resolve().parents:
        raise SystemExit(f"REFUSING: jail {jail} is inside the sandboxed container {REPO.parent}")

    sys.path.insert(0, str(REPO / "scripts"))
    G = load("grade_probe", REPO / "scripts" / "grade.py")
    GC = load("contract_probe", REPO / "scripts" / "grading_contract.py")

    slug, sid, mode = ITEM
    profile = json.loads((REPO / "profiles" / "pundits.json").read_text())
    skill = REPO / profile["skill_dir"]
    rec = json.loads((REPO / "data-pundits" / "transcripts_blind" / slug / f"{sid}.json").read_text())
    roster = {p["slug"]: p for p in json.loads((REPO / "data-pundits/roster/final.json").read_text())["roster"]}
    rec["_speaker_name"] = roster[slug]["name"]
    rec["_speaker_role"] = roster[slug]["role"]
    values = GC.prompt_values(rec, (skill / "RUBRIC.md").read_text(),
                              (skill / "judge_output.schema.json").read_text(), profile)
    baseline = GC.render_prompt((skill / "PROMPT.md").read_text(), mode, values)
    baseline_sha = hashlib.sha256(baseline.encode()).hexdigest()

    ref = json.loads((REPO / "data-pundits/grades/astra" / slug / f"{sid}__astra__{mode}__r0.json").read_text())
    run0_sha = (ref.get("identity") or {}).get("prompt_sha256")
    print(f"baseline prompt sha256 {baseline_sha[:16]} | run-0 record {str(run0_sha)[:16]} | "
          f"{'IDENTICAL' if baseline_sha == run0_sha else 'DIFFERENT — control is not the production prompt'}")
    if baseline_sha != run0_sha:
        return 2

    expect_id = f"{slug}/{sid}"
    wrapper = G.sandbox_wrapper(REPO.parent)
    results = []
    for key in [v.strip() for v in args.variants.split(",") if v.strip()]:
        desc, fn = VARIANTS[key]
        prompt = fn(baseline)
        changed = prompt != baseline
        wd = jail / "work" / key
        wd.mkdir(parents=True, exist_ok=True)
        row = {"variant": key, "description": desc, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
               "prompt_chars": len(prompt), "differs_from_baseline": changed}
        try:
            raw_in_jail = jail / f"{key}.raw.json"
            text, tel = G.call_astra(prompt, args.timeout, wd, model="gpt-6-astra",
                                     raw_response_path=raw_in_jail, wrapper=wrapper)
            (out / "raw" / f"{key}.txt").write_text(text or "")
            if raw_in_jail.exists():  # keep the record with the experiment, written by THIS process
                (out / "raw" / f"{key}.json").write_text(raw_in_jail.read_text())
            obj, errs = None, None
            start = (text or "").find("{")
            if start >= 0:
                try:
                    obj, _ = json.JSONDecoder().raw_decode(text[start:])
                except Exception as exc:  # noqa: BLE001
                    row["json_error"] = f"{type(exc).__name__}: {exc}"[:200]
            if isinstance(obj, dict):
                errs = G.validate(obj, expect_id)
                row |= {"returned_json": True, "validation_errors": errs,
                        "scored": not errs, "overall": obj.get("overall"),
                        "dimensions": {k: v.get("score") for k, v in (obj.get("dimensions") or {}).items()}}
            else:
                row |= {"returned_json": False, "scored": False, "reply_head": (text or "")[:300].replace("\n", " ")}
            row["telemetry"] = {k: tel.get(k) for k in ("served_model", "requested_model", "duration_ms") if k in tel}
        except Exception as exc:  # noqa: BLE001 -- recorded with its type, never swallowed
            row |= {"scored": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        results.append(row)
        print(f"  {key:3} {'SCORED ' if row.get('scored') else 'refused'} | {desc}"
              + (f" | overall={row.get('overall')}" if row.get("scored") else "")
              + (f" | {row.get('reply_head', row.get('error', ''))[:110]}" if not row.get("scored") else ""))
    (out / "summary.json").write_text(json.dumps(
        {"item": f"{slug}/{sid}", "mode": mode, "baseline_sha256": baseline_sha, "results": results}, indent=1))
    scored = [r["variant"] for r in results if r.get("scored")]
    print(f"\nscored: {scored or 'none'}  ({len(scored)}/{len(results)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
