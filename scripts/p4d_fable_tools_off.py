#!/usr/bin/env python3
"""P4d: how often does Fable return an unusable grade when all its tools are removed?

Pundits plan, P4. The P3 probes showed that the pundits Fable harness
(`--tools ""`, sandbox-exec, transcript audit) blocks every tool, but in one
probe Fable wrote a fake tool call as plain text instead of answering. On a
grading prompt that would be an unusable grade that still spends quota. This
measures the rate on real grading-size prompts before the flag is relied on.

WHAT IS MEASURED. The leaders grading prompt (the pundits rubric does not exist
until P5) on a seeded sample of leaders blinded transcripts, half under 10k words
and half 10k-30k words, sent through exactly the pundits Fable call:
grade.call_fable with the sandbox wrapper, --tools "" and require_no_tools.
The transcripts are read, never written; no grade enters any corpus.

OUTCOMES, one per call:
  valid            JSON that passes grade.validate
  schema_invalid   JSON that fails grade.validate
  no_json          an answer with no JSON object in it
  tool_attempt     the transcript audit found a tool call (tools were removed)
  infra            the call itself failed: quota, auth, timeout, CLI error
The unusable-answer rate is (schema_invalid + no_json + tool_attempt) over the
calls that returned an answer or a tool attempt. Infra failures are reported
separately and excluded from that denominator, because they say nothing about
how Fable answers. Each answer is also checked for a fake tool call written as
text (`<invoke` or `<function_calls>`).

Reference: the share of existing leaders Fable grades on disk that failed
validation, read-only, to put the rate in context.

Dry run by default. --run spends subscription quota.

  .venv/bin/python scripts/p4d_fable_tools_off.py --config-dir ~/.claude-e
  .venv/bin/python scripts/p4d_fable_tools_off.py --config-dir ~/.claude-e --run
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import math
import os
import random
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

UNUSABLE = ("schema_invalid", "no_json", "tool_attempt")
FAKE_TOOL_MARKERS = ("<invoke", "<function_calls>", "<tool_use")


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _binom_cdf(k: int, n: int, p: float) -> float:
    if p <= 0:
        return 1.0
    if p >= 1:
        return 0.0 if k < n else 1.0
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(0, k + 1))


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Exact two-sided interval for a binomial proportion, by bisection on the CDF."""
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0 <= k <= n:
        raise ValueError("k must be in 0..n")

    def solve(f, lo=0.0, hi=1.0):
        for _ in range(200):
            mid = (lo + hi) / 2
            if f(mid):
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2

    lower = 0.0 if k == 0 else solve(lambda p: 1 - _binom_cdf(k - 1, n, p) >= alpha / 2)
    upper = 1.0 if k == n else solve(lambda p: _binom_cdf(k, n, p) <= alpha / 2)
    return lower, upper


def classify(G, text: str | None, error: str | None, tid: str) -> dict:
    """Map one call's result onto the outcome vocabulary above."""
    if error is not None:
        label = G.classify_exception_detail(error)
        return {"outcome": "tool_attempt" if label == G.E_TOOL_ATTEMPT else "infra", "error_type": label}
    fake = any(m in (text or "") for m in FAKE_TOOL_MARKERS)
    try:
        obj = G.extract_json(text or "")
    except Exception:
        return {"outcome": "no_json", "fake_tool_text": fake}
    errs = G.validate(obj, tid)
    return {"outcome": "schema_invalid" if errs else "valid", "validation_errors": errs[:5], "fake_tool_text": fake}


def summarize(records: list[dict]) -> dict:
    counts = {o: sum(1 for r in records if r["outcome"] == o) for o in ("valid", *UNUSABLE, "infra")}
    answered = counts["valid"] + sum(counts[o] for o in UNUSABLE)
    unusable = sum(counts[o] for o in UNUSABLE)
    out = {"attempted": len(records), "counts": counts, "answered": answered, "unusable": unusable,
           "fake_tool_text": sum(1 for r in records if r.get("fake_tool_text")),
           "infra_taxonomy": {}}
    for r in records:
        if r["outcome"] == "infra":
            key = r.get("error_type") or "unknown"
            out["infra_taxonomy"][key] = out["infra_taxonomy"].get(key, 0) + 1
    if answered:
        lo, hi = clopper_pearson(unusable, answered)
        out.update(rate=round(unusable / answered, 4), ci95=[round(lo, 4), round(hi, 4)])
    else:
        out.update(rate=None, ci95=None)
    return out


def sample(rows: list[tuple[int, Path]], n_short: int, n_long: int, seed: int) -> list[Path]:
    rng = random.Random(seed)
    short = sorted(p for w, p in rows if w < 10_000)
    long_ = sorted(p for w, p in rows if 10_000 <= w < 30_000)
    if len(short) < n_short or len(long_) < n_long:
        raise SystemExit(f"not enough transcripts: {len(short)} short, {len(long_)} long")
    return rng.sample(short, n_short) + rng.sample(long_, n_long)


def reference_rate(grades_root: Path) -> dict:
    n = bad = 0
    for p in (grades_root / "fable").rglob("*.json"):
        if "_raw" in p.parts:
            continue
        try:
            r = json.loads(p.read_text())
        except ValueError:
            continue
        if r.get("refused") or "grade" not in r:
            continue
        n += 1
        bad += bool(r.get("validation_errors"))
    return {"fable_grades_on_disk": n, "failed_validation": bad, "rate": round(bad / n, 4) if n else None}


def quota_snapshot(dest: Path) -> None:
    exe = shutil.which("quotapick") or str(Path.home() / ".local/bin/quotapick")
    p = subprocess.run([exe, "status"], capture_output=True, text=True, timeout=120)
    dest.write_text(f"# {utc()} rc={p.returncode}\n{p.stdout}\n{p.stderr}")


def main() -> int:
    import grade as G
    import study_profile as SP
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config-dir", required=True, help="Claude config dir that pays. No default.")
    ap.add_argument("--n-short", type=int, default=6)
    ap.add_argument("--n-long", type=int, default=6)
    ap.add_argument("--seed", type=int, default=20260914)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=2400)
    ap.add_argument("--out", default=None, help="Default: data-pundits/logs/p4d_tools_off.")
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args()

    config_dir = str(Path(args.config_dir).expanduser())
    out_root = Path(args.out) if args.out else REPO / SP.data_link("pundits") / "logs" / "p4d_tools_off"
    SP.guard("pundits", out_root)
    source = REPO / "data" / "transcripts_blind"
    rows = []
    for p in sorted(source.rglob("*.json")):
        r = json.loads(p.read_text())
        rows.append((r.get("word_count") or len(r["text"].split()), p))
    chosen = sample(rows, args.n_short, args.n_long, args.seed)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    run_dir = out_root / run_id
    container = REPO.parent.resolve()
    wrapper = G.sandbox_wrapper(container)
    rubric, schema = G.RUBRIC_PATH.read_text(), G.SCHEMA_PATH.read_text()
    ref = reference_rate(REPO / "data" / "grades")

    print(f"run {run_id}: {len(chosen)} Fable calls ({args.n_short} under 10k words, {args.n_long} 10k-30k), "
          f"seed {args.seed}, {args.workers} workers, pays from {config_dir}")
    print(f"  harness: sandbox-exec denying {container}, --tools \"\", transcript audit required")
    print(f"  reference: {ref['failed_validation']}/{ref['fable_grades_on_disk']} existing leaders Fable grades "
          f"failed validation (rate {ref['rate']})")
    for p in chosen:
        print(f"  - {p.parent.name}/{p.stem}")
    if not args.run:
        print("dry run: no model was called. Add --run to spend quota.")
        return 0

    (run_dir / "raw").mkdir(parents=True)
    quota_snapshot(run_dir / "quota_before.txt")
    jail_root = Path(os.environ.get("TMPDIR", "/tmp")) / f"p4d-jail-{run_id}"

    def one(path: Path) -> dict:
        rec = json.loads(path.read_text())
        tid = f"{rec['leader_slug']}/{rec['source_id']}"
        prompt = G.build_judge_prompt(rec, "blinded", rubric, schema)
        jail = jail_root / f"{rec['leader_slug']}-{rec['source_id']}"
        jail.mkdir(parents=True, exist_ok=True)
        started, text, tel, error = utc(), None, {}, None
        try:
            text, tel = G.call_fable(prompt, config_dir, args.timeout, "claude", str(jail),
                                     wrapper=wrapper, extra_args=["--tools", ""], require_no_tools=True)
        except subprocess.TimeoutExpired:
            error = f"{G.E_TIMEOUT}: exceeded {args.timeout}s"
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
        result = {"transcript_id": tid, "word_count": rec.get("word_count"), "started_at_utc": started,
                  "finished_at_utc": utc(), **classify(G, text, error, tid), "error": (error or "")[:600],
                  "telemetry": tel, "answer_head": (text or "")[:400], "answer_chars": len(text or "")}
        (run_dir / "raw" / f"{rec['leader_slug']}__{rec['source_id']}.json").write_text(
            json.dumps({**result, "answer": text}, indent=1))
        print(f"  [{result['finished_at_utc']}] {result['outcome']:15} {tid} "
              f"({result['word_count']} words){' FAKE-TOOL-TEXT' if result.get('fake_tool_text') else ''}",
              flush=True)
        return result

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        records = list(ex.map(one, chosen))
    quota_snapshot(run_dir / "quota_after.txt")
    summary = {"run_id": run_id, "config_dir": config_dir, "seed": args.seed, "sandbox_root": str(container),
               "harness": {"wrapper": "sandbox-exec", "extra_args": ["--tools", ""], "require_no_tools": True},
               "reference_leaders_fable": ref, **summarize(records),
               "by_length": {band: summarize([r for r in records if (r["word_count"] or 0) < 10_000] if band == "under_10k"
                                             else [r for r in records if (r["word_count"] or 0) >= 10_000])
                             for band in ("under_10k", "10k_30k")}}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: summary[k] for k in ("attempted", "counts", "answered", "unusable", "rate", "ci95",
                                              "fake_tool_text", "infra_taxonomy", "reference_leaders_fable")},
                     indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
