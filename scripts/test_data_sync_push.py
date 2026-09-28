#!/usr/bin/env python3
"""`data_sync.py push`: two contributor clones push the data repo's main without
clobbering each other.

Plan: docs/plans/shared-data-push-2026-09-27.md, phase P2. Every scenario runs
real git: a bare remote, two or three clones, real records that pass
validate_predictions, and the real aggregate and scoring code.

  MERGE     A and B each add a transcript and its records from stale clones; both
            land, their commits stay reachable, and the index and scores on
            origin/main are fresh. B also committed its own regenerated index,
            which conflicts with A's (merge=binary): the tool regenerates it.
  PINNED    a run manifest's input_data_commit is still reachable after the push,
            which a rebase would break.
  RECORDS   A and B each edit a different record in the SAME file: git would merge
            the lines cleanly; the tool refuses and names the file.
  SIDECAR   A and B resolve the same prediction in two runs: every file merges
            cleanly, the scorer refuses the duplicate, so the push refuses.
  VALIDATE  a record whose contract no run manifest names is refused, naming the
            invariant, while a failure that already existed does not block.
  RETRY     origin/main moving between fetch and push is retried; three moves in
            a row stop the push with a report.
  REFUSE    an owner path, a dirty tracked tree, or a non-main branch refuses, and
            every refusal leaves HEAD exactly where it was.

  .venv/bin/python scripts/test_data_sync_push.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
TEMPLATES = REPO / "data-repo-templates" / "leaders"
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def load(name: str):
    sys.path.insert(0, str(REPO / "scripts"))
    spec = importlib.util.spec_from_file_location(f"{name}_dsp", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L = load("predictions_lib")
R = load("resolution_lib")
S = load("data_sync")


def git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr}")
    return p.stdout.strip()


def add_transcript(data: Path, root: str, slug: str, sid: str, quotes: list[str],
                   contract: str = "a" * 12) -> list[str]:
    """A transcript and its records, the way extraction writes them. Returns ids."""
    text = "[00:00:01] intro words here [00:01:00] " + " and then ".join(quotes) + " and more words follow after that"
    src = {"leader_slug": slug, "source_id": sid, "text": text, "yt_upload_date": "20190301", "url": "u",
           "video_id": "v", "yt_title": "T", "declared_venue": "V", "declared_kind": "podcast",
           "word_count": 30, "duration_sec": 60}
    (data / root / slug).mkdir(parents=True, exist_ok=True)
    (data / root / slug / f"{sid}.json").write_text(json.dumps(src))
    recs = []
    for q in quotes:
        cand = {"quote": q, "gates": {g: True for g in L.GATES}, "gate_notes": "", "resolution_criteria": "By 2020, Y",
                "normalized_claim": "c", "category": "ai_capability", "prediction_type": "milestone",
                "target_date": "2020", "target_date_text": "by 2020", "horizon": "explicit",
                "horizon_years_inferred": None, "horizon_evidence": None, "specificity": "high",
                "subject_control": "external",
                "confidence": {"type": "none", "probability": None, "verbatim_confidence_language": None}}
        prov = L.normalise_provenance("fable", {"requested_model": "claude-fable-5-1",
                                                "judge_model": "claude-fable-5-1[1m]"}, "default", "claude")
        r = L.make_record(src, {"name": slug.title(), "role": "CEO", "company": "Co"}, cand,
                          L.locate_quote(text, q), prov, contract, "run-x", "2026-09-10T00:00:00Z", {})
        v = r["verification"]
        v.update({"status": "ok", "harness": "astra", "requested_model": "gpt-6-astra", "served_model": "gpt-6-astra",
                  "served_model_verified": False, "account": "codex", "router_account_id": "codex",
                  "contract_id": contract, "run_id": "run-v", "verified_at_utc": "2026-09-10T01:00:00Z",
                  "gates": {g: True for g in L.GATES}, "attribution": "subject", "claim_faithful": True,
                  "qualifies_stated": True, "verifier_resolution_criteria": "x", "notes": None, "telemetry": {}})
        v["qualifies"] = L.verification_qualifies(v)
        v["agreement"] = r["extraction"]["qualifies"] == v["qualifies"]
        r["accepted"] = L.compute_accepted(r)
        recs.append(r)
    write_records(data, slug, sid, recs)
    return [r["prediction_id"] for r in recs]


def write_records(data: Path, slug: str, sid: str, recs: list[dict]) -> None:
    (data / "predictions" / slug).mkdir(parents=True, exist_ok=True)
    (data / "predictions" / slug / f"{sid}.jsonl").write_text(L.serialise_lines(recs))
    (data / "predictions" / slug / f"{sid}.meta.json").write_text(json.dumps(
        {"schema_version": 1, "transcript_id": f"{slug}/{sid}",
         "extract": {"status": "ok", "harness": "fable", "candidates_written": len(recs), "cap_hit": False,
                     "ungrounded": [], "dedupe_dropped": []},
         "verify": {"status": "ok", "harness": "astra", "accepted": sum(1 for r in recs if r.get("accepted") is True)}},
        sort_keys=True))


def read_records(data: Path, slug: str, sid: str) -> list[dict]:
    return L.parse_lines((data / "predictions" / slug / f"{sid}.jsonl").read_text(), "x")


def sidecar(data: Path, run: str, pid: str) -> None:
    root = data / "predictions" / "_experiments" / run
    res = {"prediction_id": pid, "leader_slug": "ada", "transcript_id": "ada/s1", "stage": "resolve",
           "outcome": "occurred", "confidence": "high", "unresolvable_reason": None, "reasoning": "r",
           "sources": [{"where": "u", "what_it_shows": "w", "date": None}], "deadline": "2020-12-31"}
    pri = {"prediction_id": pid, "leader_slug": "ada", "transcript_id": "ada/s1", "stage": "prior",
           "p": 0.5, "p_raw": 0.5, "clamped": False, "reference_class": "rc", "reasoning": "r"}
    for stage, obj in (("resolve", res), ("prior", pri)):
        fp = R.sidecar_path(root, stage, "ada", pid)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(obj))


Q = ["by 2020 most new code will be written by machines, I am sure",
     "open models will catch up with the closed ones by 2020, I think",
     "robots will be folding laundry in most homes by 2020, I believe",
     "we will see the first fully autonomous taxi service by 2020 here"]


def seed(td: Path) -> tuple[Path, dict]:
    remote = td / "remote.git"
    git(td, "init", "-q", "--bare", "-b", "main", str(remote))
    s = td / "seed"
    git(td, "clone", "-q", str(remote), str(s))
    for k, v in (("user.email", "t@example.com"), ("user.name", "T"), ("verbatim.role", "daemon")):
        git(s, "config", k, v)
    shutil.copy(TEMPLATES / "ownership.json", s / "ownership.json")
    shutil.copy(TEMPLATES / ".gitattributes", s / ".gitattributes")
    (s / "roster").mkdir()
    (s / "roster" / "final.json").write_text(json.dumps({"roster": [
        {"slug": "ada", "name": "Ada L", "company": "Co", "role": "CEO", "sector": "AI"},
        {"slug": "alan", "name": "Alan T", "company": "Lab", "role": "Founder", "sector": "AI"}]}))
    ids = {"s1": add_transcript(s, "transcripts_open", "ada", "s1", Q[:2])}
    (s / "transcripts_web").mkdir()
    (s / "transcripts_web" / ".keep").write_text("")
    (s / "predictions" / "_runs").mkdir(parents=True)
    (s / "predictions" / "_runs" / "run-x.json").write_text(json.dumps({"extraction_contract": {"contract_id": "a" * 12}}))
    (s / "predictions" / "scoring.json").write_text(json.dumps({
        "as_of": "2026-09-16", "trend": True, "min_lead_days": 60, "predictions": ["predictions"],
        "runs": ["predictions/_experiments/run-1", "predictions/_experiments/run-2"],
        "index": "predictions/index.json", "out": "predictions/scores.json"}, indent=1, sort_keys=True) + "\n")
    git(s, "add", "-A")
    git(s, "commit", "-q", "-m", "seed inputs")
    for rel, data in S.regenerate(s, "HEAD").items():
        (s / rel).write_bytes(data)
    git(s, "add", "-A")
    git(s, "commit", "-q", "-m", "seed derived files")
    git(s, "push", "-q", "origin", "main")
    return remote, ids


def clone(td: Path, remote: Path, name: str, role: str = "contributor") -> Path:
    c = td / name
    git(td, "clone", "-q", str(remote), str(c))
    for k, v in (("user.email", "t@example.com"), ("user.name", "T"), ("verbatim.role", role)):
        git(c, "config", k, v)
    return c


def commit(c: Path, msg: str) -> str:
    git(c, "add", "-A")
    git(c, "commit", "-q", "-m", msg)
    return git(c, "rev-parse", "HEAD")


def push(c: Path, env: dict | None = None):
    return subprocess.run([PY, str(REPO / "scripts" / "data_sync.py"), "push", "--data", str(c)],
                          capture_output=True, text=True, cwd=REPO, env={**os.environ, **(env or {})})


def fresh_on_remote(td: Path, remote: Path, name: str) -> list[str]:
    v = clone(td, remote, name)
    return S.derived_problems(v, "origin/main")


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        remote, ids = seed(td)
        check("SEED: the seeded remote's derived files are fresh", fresh_on_remote(td, remote, "v0") == [],
              str(fresh_on_remote(td, remote, "v0b")))

        # ------------------------------------------------------------ MERGE --
        a, b = clone(td, remote, "a"), clone(td, remote, "b")
        add_transcript(a, "transcripts_web", "alan", "w1", [Q[2]])
        a_commit = commit(a, "A: alan's web transcript and its record")
        p = push(a)
        check("MERGE: A pushes onto an unchanged main", p.returncode == 0, p.stdout + p.stderr[-600:])

        add_transcript(b, "transcripts_web", "ada", "w2", [Q[3]])
        run_manifest = b / "predictions" / "_experiments" / "run-b" / "experiment.json"
        run_manifest.parent.mkdir(parents=True)
        run_manifest.write_text(json.dumps({"input_data_commit": git(b, "rev-parse", "HEAD")}))
        pinned = git(b, "rev-parse", "HEAD")
        b_commit = commit(b, "B: ada's web transcript and a run manifest")
        for rel, data in S.regenerate(b, "HEAD").items():  # B regenerates from its own commit,
            (b / rel).write_bytes(data)                    # so its index.json conflicts with A's
        commit(b, "B's own regenerated index")
        p = push(b)
        check("MERGE: B pushes from a stale clone, after a conflicting index regeneration",
              p.returncode == 0, p.stdout + p.stderr[-600:])
        check("MERGE: B's own index really conflicted with A's, and was resolved by regenerating",
              "derived conflict in predictions/index.json" in p.stdout and "regenerated" in p.stdout, p.stdout)
        v = clone(td, remote, "v1")
        on_main = git(v, "rev-parse", "origin/main")
        reach = lambda sha: subprocess.run(["git", "merge-base", "--is-ancestor", sha, on_main], cwd=v).returncode == 0  # noqa: E731
        check("MERGE: both contributors' commits are on main", reach(a_commit) and reach(b_commit))
        check("MERGE: the derived files on main are fresh", S.derived_problems(v, "origin/main") == [],
              str(S.derived_problems(v, "origin/main")))
        idx = json.loads((v / "predictions" / "index.json").read_text())
        check("MERGE: the index counts both new transcripts", idx["files_read"] == 3, str(idx["files_read"]))
        check("PINNED: a run's input_data_commit is still reachable from main", reach(pinned))

        # ---------------------------------------------------------- RECORDS --
        a2, b2 = clone(td, remote, "a2"), clone(td, remote, "b2")
        recs = read_records(a2, "ada", "s1")
        recs[0]["prediction"]["normalized_claim"] = "edited by A"
        write_records(a2, "ada", "s1", recs)
        commit(a2, "A edits record 1 of ada/s1")
        p = push(a2)
        check("RECORDS: A's in-place record edit lands", p.returncode == 0, p.stdout + p.stderr[-600:])
        recs = read_records(b2, "ada", "s1")
        recs[1]["prediction"]["normalized_claim"] = "edited by B"
        write_records(b2, "ada", "s1", recs)
        before = commit(b2, "B edits record 2 of ada/s1")
        main_before = git(clone(td, remote, "v2"), "rev-parse", "origin/main")
        p = push(b2)
        check("RECORDS: two edits to one record file refuse, naming it",
              p.returncode != 0 and "predictions/ada/s1.jsonl" in p.stdout and "changed on both sides" in p.stdout,
              p.stdout + p.stderr[-600:])
        check("REFUSE: the refusal leaves B's HEAD where it was", git(b2, "rev-parse", "HEAD") == before)
        check("REFUSE: nothing reached main", git(clone(td, remote, "v3"), "rev-parse", "origin/main") == main_before)

        # ---------------------------------------------------------- SIDECAR --
        a3, b3 = clone(td, remote, "a3"), clone(td, remote, "b3")
        pid = ids["s1"][0]
        sidecar(a3, "run-1", pid)
        commit(a3, "A resolves a prediction in run-1")
        p = push(a3)
        check("SIDECAR: A's resolution lands and scores regenerate", p.returncode == 0, p.stdout + p.stderr[-600:])
        sidecar(b3, "run-2", pid)
        before = commit(b3, "B resolves the same prediction in run-2")
        p = push(b3)
        check("SIDECAR: the same prediction resolved in two runs refuses, naming both runs",
              p.returncode != 0 and "two runs" in p.stdout and pid in p.stdout, p.stdout + p.stderr[-600:])
        check("REFUSE: the sidecar refusal leaves B's HEAD where it was", git(b3, "rev-parse", "HEAD") == before)

        # --------------------------------------------------------- VALIDATE --
        c4 = clone(td, remote, "c4")
        add_transcript(c4, "transcripts_web", "alan", "w3", [Q[0]], contract="c" * 12)
        before = commit(c4, "a record whose contract no run manifest names")
        p = push(c4)
        check("VALIDATE: a record with an unknown contract refuses, naming the invariant and file",
              p.returncode != 0 and "provenance" in p.stdout and "predictions/alan/w3.jsonl" in p.stdout,
              p.stdout + p.stderr[-600:])
        (c4 / "predictions" / "_runs" / "run-c.json").write_text(
            json.dumps({"extraction_contract": {"contract_id": "c" * 12}}))
        commit(c4, "its run manifest")
        p = push(c4)
        check("VALIDATE: adding the run manifest makes it pass", p.returncode == 0, p.stdout + p.stderr[-600:])

        # ------------------------------------------------------------ RETRY --
        racer = clone(td, remote, "racer")
        hook = td / "race.sh"
        hook.write_text(
            "#!/bin/sh\n"
            f"cd {racer} && git pull -q --no-rebase origin main && "
            "echo $DATA_SYNC_ATTEMPT-$$ > predictions/_experiments/race-$DATA_SYNC_ATTEMPT-$$.txt && "
            "git add -A && git commit -q -m race && git push -q origin main\n")
        hook.chmod(0o755)
        (racer / "predictions" / "_experiments").mkdir(parents=True, exist_ok=True)
        c5 = clone(td, remote, "c5")
        (c5 / "predictions" / "_experiments" / "c5.txt").write_text("c5")
        commit(c5, "c5 work")
        p = push(c5, {"DATA_SYNC_TEST_BEFORE_PUSH": str(hook), "DATA_SYNC_TEST_BEFORE_PUSH_TIMES": "1"})
        check("RETRY: main moving once between fetch and push is retried and lands",
              p.returncode == 0 and "attempt 2" in p.stdout, p.stdout + p.stderr[-600:])
        c6 = clone(td, remote, "c6")
        (c6 / "predictions" / "_experiments" / "c6.txt").write_text("c6")
        before = commit(c6, "c6 work")
        p = push(c6, {"DATA_SYNC_TEST_BEFORE_PUSH": str(hook), "DATA_SYNC_TEST_BEFORE_PUSH_TIMES": "99"})
        check("RETRY: three moves in a row stop the push, and the report counts the attempts",
              p.returncode != 0 and "attempted 3" in p.stdout and "non_fast_forward" in p.stdout,
              p.stdout + p.stderr[-600:])
        check("REFUSE: after the retries the HEAD is back where it was", git(c6, "rev-parse", "HEAD") == before)

        # ----------------------------------------------------------- REFUSE --
        c7 = clone(td, remote, "c7")
        (c7 / "roster" / "final.json").write_text((c7 / "roster" / "final.json").read_text().replace("Lab", "Lab2"))
        before = commit(c7, "an owner path")
        p = push(c7)
        check("REFUSE: an owner path refuses, naming it", p.returncode != 0 and "roster/final.json" in p.stdout,
              p.stdout + p.stderr[-600:])
        check("REFUSE: and HEAD is where it was", git(c7, "rev-parse", "HEAD") == before)
        git(c7, "reset", "-q", "--hard", "origin/main")
        (c7 / "predictions" / "scoring.json").write_text("{}")  # tracked, unstaged
        p = push(c7)
        check("REFUSE: a dirty tracked tree refuses", p.returncode != 0 and "uncommitted" in p.stdout,
              p.stdout + p.stderr[-600:])
        git(c7, "checkout", "-q", "--", "predictions/scoring.json")
        git(c7, "switch", "-q", "-c", "side")
        p = push(c7)
        check("REFUSE: a branch other than main refuses", p.returncode != 0 and "main" in p.stdout,
              p.stdout + p.stderr[-600:])

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
