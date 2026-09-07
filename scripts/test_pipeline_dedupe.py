#!/usr/bin/env python3
"""Guards for the duplicate-transcript bugs found on 2026-09-07.

A roster-wide near-duplicate scan of `data/transcripts_blind` found 15 second
copies of an appearance that was already in the graded set, across 10 leaders.
Reed Hastings' Greylock talk was there three times, so one appearance carried
three times the weight of anyone else's, and removing the extra copies moved
him 3.2 points and four ranks.

`dedupe_transcripts.py` was not at fault. It scored every one of those pairs
above its threshold. Two other things let them through, and each test below
names the one it guards.

  .venv/bin/python scripts/test_pipeline_dedupe.py
  DEDUPE_SCAN=1 .venv/bin/python scripts/test_pipeline_dedupe.py   # also scan the live corpus
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = str(Path(sys.executable))


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_mod", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if detail and not ok:
        print(f"          {detail}")


# ---------------------------------------------------------------------------
# A miniature corpus. Two leaders, three transcripts, enough grades to tell a
# pruned one from a kept one and a blinded grade from an open one.
# ---------------------------------------------------------------------------

ROSTER = {"roster": [
    {"slug": "ada-lovelace", "name": "Ada Lovelace", "company": "Analytical Engines", "role": "CEO"},
    {"slug": "alan-turing", "name": "Alan Turing", "company": "Bletchley", "role": "CTO"},
]}

CORPUS = [
    ("ada-lovelace", "keynote-aaa"),
    ("ada-lovelace", "reupload-bbb"),   # the duplicate copy the sweep retires
    ("alan-turing", "lecture-ccc"),
]


def build(tmp: Path) -> dict:
    """Lay out transcripts, roster and grades the way the real pipeline does."""
    src = tmp / "transcripts"
    for slug, sid in CORPUS:
        d = src / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{sid}.json").write_text(json.dumps({
            "leader_slug": slug, "source_id": sid, "url": f"https://example.test/{sid}",
            "declared_title": sid, "word_count": 120, "duration_sec": 600,
            "fetched_at_utc": "2026-09-06T00:00:00Z",
            "text": f"[00:00:01] Ada Lovelace of Analytical Engines speaks here about {sid}. " * 12,
        }, indent=1))

    roster = tmp / "roster.json"
    roster.write_text(json.dumps(ROSTER))

    grades = tmp / "grades"
    for slug, sid in CORPUS:
        for judge in ("fable", "astra"):
            for mode in ("blinded", "open"):
                d = grades / judge / slug
                d.mkdir(parents=True, exist_ok=True)
                (d / f"{sid}__{judge}__{mode}__r0.json").write_text(json.dumps({
                    "transcript_id": f"{slug}/{sid}", "leader_slug": slug, "source_id": sid,
                    "judge": judge, "mode": mode, "run": 0,
                    "grade": {"dimensions": {d_: {"score": 50} for d_ in
                                             ("d1_clarity", "d2_insight", "d3_technical_depth")},
                              "coverage": 0.9, "subject_speech_share_pct": 80, "overall": 50.0},
                }, indent=1))
    return {"src": src, "roster": roster, "grades": grades}


def normalize(env: dict, out: Path, tmp: Path, mode: str = "blinded",
              qa: Path | None = None, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    cmd = [PY, str(REPO / "scripts" / "normalize_transcripts.py"),
           "--transcripts", str(env["src"]), "--out", str(out),
           "--roster", str(env["roster"]), "--mode", mode,
           "--log", str(tmp / f"normalize_{mode}.json")]
    if qa:
        cmd += ["--qa", str(qa)]
    cmd += extra or []
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)


def outputs(out: Path) -> set[str]:
    return {f"{p.parent.name}/{p.stem}" for p in out.rglob("*.json") if not p.name.endswith(".json.tmp")}


def live_grades(grades: Path, mode: str) -> set[str]:
    """Grade files aggregate.py would still load, i.e. not renamed to .orphaned."""
    return {p.name for p in grades.rglob("*.json") if f"__{mode}__" in p.name}


# ---------------------------------------------------------------------------
# 1. A retired source must take its derived transcript with it.
#
# Observed 2026-09-07: 8 files in data/transcripts_blind had no source left in
# data/transcripts. dedupe_transcripts.py --sweep had retired those sources as
# duplicates. normalize_transcripts.py contains no delete path of any kind, so
# grade.py, which globs the whole output directory, kept grading them.
#   fei-fei-li/radical-ventures-e14isf     lisa-su/reuters-p4lkux
#   lisa-su/yahoo-finance-wjh-u8           matthew-prince/all-hacking-cons-y7c-mo
#   michael-dell/zenvora-productions-lzc4lz  reed-hastings/startupacademy-q5jk3y
#   reed-hastings/tehdrek-egxqp3           yann-lecun/hs-416-yann-lecun-...
# ---------------------------------------------------------------------------

def test_retired_source_is_pruned(tmp: Path) -> None:
    print("\n[1] a retired source takes its derived transcript with it")
    env = build(tmp)
    out = tmp / "blind"
    normalize(env, out, tmp, extra=["--grades", str(env["grades"])])
    check("normalize writes one derived transcript per source",
          outputs(out) == {"ada-lovelace/keynote-aaa", "ada-lovelace/reupload-bbb",
                           "alan-turing/lecture-ccc"}, f"outputs={sorted(outputs(out))}")

    # The sweep retires the duplicate, exactly as dedupe_transcripts.py does.
    (env["src"] / "ada-lovelace" / "reupload-bbb.json").rename(
        env["src"] / "ada-lovelace" / "reupload-bbb.json.superseded")

    r = normalize(env, out, tmp, extra=["--grades", str(env["grades"])])
    check("the second normalize run exits clean", r.returncode == 0, r.stderr[-400:])
    check("the derived copy of the retired source is gone",
          outputs(out) == {"ada-lovelace/keynote-aaa", "alan-turing/lecture-ccc"},
          f"outputs={sorted(outputs(out))}")
    check("the transcripts that are still on the shelf are untouched",
          (out / "ada-lovelace" / "keynote-aaa.json").exists()
          and (out / "alan-turing" / "lecture-ccc.json").exists())


# ---------------------------------------------------------------------------
# 2. Deleting the derived transcript is not enough on its own.
#
# aggregate.py walks data/grades and never looks at data/transcripts_blind, so
# a retired appearance keeps scoring until its grades go too. The sweep does
# have an orphan step, but it only fires for sources retired in that same run,
# and `find data/grades -name '*.orphaned'` returned 0 against 8 stale files.
# ---------------------------------------------------------------------------

def test_orphaned_grades_stop_counting(tmp: Path) -> None:
    print("\n[2] a retired source stops counting toward the leaderboard")
    env = build(tmp)
    out = tmp / "blind"
    normalize(env, out, tmp, extra=["--grades", str(env["grades"])])
    (env["src"] / "ada-lovelace" / "reupload-bbb.json").unlink()
    normalize(env, out, tmp, extra=["--grades", str(env["grades"])])

    agg = load("aggregate")
    loaded = {(g["source_id"], g["mode"]) for g in agg.load_grades(env["grades"])}
    check("aggregate.py no longer loads the retired transcript's blinded grades",
          ("reupload-bbb", "blinded") not in loaded, f"loaded={sorted(loaded)}")
    check("the retired grades are renamed rather than deleted, so the choice is auditable",
          len(list(env["grades"].rglob("*.orphaned"))) == 2,
          f"orphaned={[p.name for p in env['grades'].rglob('*.orphaned')]}")
    check("the surviving transcripts keep every grade",
          {("keynote-aaa", "blinded"), ("lecture-ccc", "blinded")} <= loaded)


# ---------------------------------------------------------------------------
# 3. A blinded run must not orphan the open-mode control grades.
#
# normalize runs twice over the same corpus, into two different output
# directories. A prune that ignored mode would have each run delete the other's
# grades, and the halo measurement would vanish.
# ---------------------------------------------------------------------------

def test_prune_is_scoped_to_its_own_mode(tmp: Path) -> None:
    print("\n[3] pruning a blinded run leaves the open-mode grades alone")
    env = build(tmp)
    out = tmp / "blind"
    normalize(env, out, tmp, mode="blinded", extra=["--grades", str(env["grades"])])
    (env["src"] / "ada-lovelace" / "reupload-bbb.json").unlink()
    normalize(env, out, tmp, mode="blinded", extra=["--grades", str(env["grades"])])

    check("the blinded grades of the retired transcript are orphaned",
          not any("reupload-bbb" in p.name for p in
                  env["grades"].rglob("*__blinded__*.json")))
    check("its open-mode grades are still there for the open pass to prune",
          len([p for p in env["grades"].rglob("*__open__*.json")
               if "reupload-bbb" in p.name]) == 2,
          f"open={[p.name for p in env['grades'].rglob('*__open__*.json')]}")


# ---------------------------------------------------------------------------
# 4. A transcript that QA rejects leaks in exactly the same way.
#
# normalize skips a rejected transcript with `continue`, which leaves any copy
# written on an earlier run in place and gradeable. Same defect as [1], a
# different trigger, so it needs its own guard.
# ---------------------------------------------------------------------------

def test_qa_rejected_transcript_is_pruned(tmp: Path) -> None:
    print("\n[4] a transcript QA rejects is withdrawn, not just skipped")
    env = build(tmp)
    out = tmp / "blind"
    normalize(env, out, tmp, extra=["--grades", str(env["grades"])])

    qa = tmp / "qa.json"
    qa.write_text(json.dumps({"reports": [
        {"leader_slug": "alan-turing", "source_id": "lecture-ccc", "verdict": "reject"}]}))
    normalize(env, out, tmp, qa=qa, extra=["--grades", str(env["grades"])])

    check("the rejected transcript's derived copy is removed",
          "alan-turing/lecture-ccc" not in outputs(out), f"outputs={sorted(outputs(out))}")
    check("its blinded grades stop counting",
          not any("lecture-ccc" in p.name for p in env["grades"].rglob("*__blinded__*.json")))


# ---------------------------------------------------------------------------
# 5. A prune that would empty the corpus must refuse, loudly.
#
# Pruning trusts the source directory. If a fetch loop has data/transcripts
# half-written, or a path argument is wrong, an unguarded prune deletes the
# whole blinded corpus and orphans every grade in one silent pass. This is the
# accept-and-guess failure the repo rules forbid, so it fails instead.
# ---------------------------------------------------------------------------

def test_mass_prune_refuses(tmp: Path) -> None:
    print("\n[5] a prune large enough to be a mistake refuses instead of guessing")
    env = build(tmp)
    # A corpus big enough to clear the guard's absolute floor.
    for i in range(20):
        d = env["src"] / "ada-lovelace"
        (d / f"filler-{i:02d}.json").write_text(json.dumps({
            "leader_slug": "ada-lovelace", "source_id": f"filler-{i:02d}",
            "word_count": 50, "text": "[00:00:01] Ada Lovelace of Analytical Engines. " * 20,
        }, indent=1))
    out = tmp / "blind"
    normalize(env, out, tmp, extra=["--grades", str(env["grades"])])
    before = outputs(out)
    check("the guard test starts from a corpus worth protecting", len(before) == 23,
          f"n={len(before)}")

    empty = tmp / "empty"
    empty.mkdir()
    r = subprocess.run(
        [PY, str(REPO / "scripts" / "normalize_transcripts.py"),
         "--transcripts", str(empty), "--out", str(out), "--roster", str(env["roster"]),
         "--mode", "blinded", "--grades", str(env["grades"]),
         "--log", str(tmp / "normalize_guard.json")],
        capture_output=True, text=True, cwd=REPO)
    check("normalize exits non-zero rather than emptying the corpus", r.returncode != 0,
          f"rc={r.returncode}")
    check("the refusal says how much it would have removed",
          "23" in (r.stderr + r.stdout), (r.stderr + r.stdout)[-400:])
    check("nothing was deleted", outputs(out) == before,
          f"lost={sorted(before - outputs(out))}")
    check("no grade was orphaned", not list(env["grades"].rglob("*.orphaned")))


# ---------------------------------------------------------------------------
# 6. The duplicate sweep must run in the loop that feeds the graders.
#
# Observed 2026-09-07: `dedupe_transcripts.py --sweep` was called only from
# happyscribe_loop.sh. fetch_loop.sh adds YouTube transcripts and grade_loop.sh
# grades them, and neither swept. Almost every duplicate found was one talk
# re-uploaded to several YouTube channels, which is precisely what arrives
# through the loop that never swept. A dry run of the sweep against the corpus
# would have retired 16 transcripts at that moment.
# ---------------------------------------------------------------------------

def commands(name: str) -> list[str]:
    """The runnable command lines of a shell script, comments and blanks dropped.

    Continuation lines are joined first. The earlier version of this test read
    the script line by line, so it never saw a redirect that sat on the line
    after the command, and a `>/dev/null` added there passed unnoticed.
    """
    raw = (REPO / "scripts" / name).read_text()
    joined, buf = [], ""
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        buf += " " + stripped
        if stripped.endswith("\\"):
            buf = buf[:-1]
            continue
        if buf.strip():
            joined.append(" ".join(buf.split()))
        buf = ""
    return joined


def only(cmds: list[str], needle: str) -> list[str]:
    return [c for c in cmds if needle in c]


def test_sweep_runs_before_grading() -> None:
    print("\n[6] the duplicate sweep runs before anything is graded")
    cmds = commands("grade_loop.sh")
    i_sweep = [i for i, c in enumerate(cmds) if "dedupe_transcripts.py --sweep" in c]
    i_norm = [i for i, c in enumerate(cmds) if "normalize_transcripts.py" in c]
    i_grade = [i for i, c in enumerate(cmds) if "grade.py" in c]
    check("grade_loop.sh runs the duplicate sweep, in a command and not a comment",
          len(i_sweep) == 1, f"found {len(i_sweep)} sweep commands")
    check("it copies transcripts and grades them", i_norm and i_grade,
          f"normalize={i_norm} grade={i_grade}")
    check("the sweep runs before the transcripts are copied for grading",
          bool(i_sweep) and bool(i_norm) and i_sweep[0] < min(i_norm),
          f"sweep@{i_sweep} normalize@{i_norm}")
    check("the copying runs before the grading",
          bool(i_norm) and bool(i_grade) and min(i_norm) < min(i_grade),
          f"normalize@{i_norm} grade@{i_grade}")


# ---------------------------------------------------------------------------
# 7. The sweep's report is the only record of what it removed.
#
# happyscribe_loop.sh sent it to /dev/null, so `sweep_retired` and
# `orphaned_grades_removed` were never written anywhere.
#
# The first version of this test read one line at a time, which is exactly the
# hole an adversarial review walked through: in grade_loop.sh the redirect sits
# on the continuation line, so `>/dev/null` there passed. It now reads whole
# commands, and it asserts the sweep exists first, so removing the sweep makes
# the test fail rather than making the check disappear.
# ---------------------------------------------------------------------------

def test_sweep_report_is_kept() -> None:
    print("\n[7] the sweep's report is kept, not discarded")
    for name in ("grade_loop.sh", "happyscribe_loop.sh"):
        sweeps = only(commands(name), "dedupe_transcripts.py --sweep")
        check(f"{name} still calls the sweep", len(sweeps) == 1, f"found {len(sweeps)}")
        for c in sweeps:
            check(f"{name} does not send the sweep report to /dev/null",
                  "/dev/null" not in c.split("2>>")[0], c)


# ---------------------------------------------------------------------------
# 7b. Only one daemon may prune, and the prune must re-check the shelf.
#
# FOUND BY ADVERSARIAL REVIEW of a78baf5, and reproduced. fetch_loop.sh and
# grade_loop.sh both run normalize over the same two directories at the same
# time. normalize lists --transcripts ONCE at the top, so a transcript that
# lands between that listing and the prune is absent from `kept` and was
# deleted, and its grades orphaned, while its source sat on the shelf. Before
# a78baf5 normalize only ever wrote files, so concurrency was harmless. The
# commit made it destructive.
#
# Two guards, because either alone leaves a window. The prune re-checks the
# shelf at deletion time, and only the grading loop prunes at all.
# ---------------------------------------------------------------------------

def test_only_one_loop_prunes() -> None:
    print("\n[7b] only the grading loop prunes, and the fetch loop cannot")
    fetch = only(commands("fetch_loop.sh"), "normalize_transcripts.py")
    grade = only(commands("grade_loop.sh"), "normalize_transcripts.py")
    check("fetch_loop.sh normalizes without pruning",
          fetch and all("--no-prune" in c for c in fetch), f"{fetch}")
    check("fetch_loop.sh cannot orphan grades", all("--grades" not in c for c in fetch), f"{fetch}")
    check("grade_loop.sh does prune, and can orphan grades",
          grade and all("--no-prune" not in c and "--grades" in c for c in grade), f"{grade}")


def test_prune_rechecks_the_shelf(tmp: Path) -> None:
    print("\n[7c] a transcript that arrives mid-run is not deleted by a stale listing")
    env = build(tmp)
    out = tmp / "blind"
    normalize(env, out, tmp, extra=["--grades", str(env["grades"])])

    # Simulate the race directly: a derived copy and its grades exist for a
    # source that IS on the shelf but was not written by this run, exactly the
    # state a concurrent fetch_loop normalize leaves behind.
    d = env["src"] / "alan-turing"
    (d / "arrived-late.json").write_text(json.dumps({
        "leader_slug": "alan-turing", "source_id": "arrived-late",
        "word_count": 40, "text": "[00:00:01] Alan Turing of Bletchley on machinery. " * 20,
    }, indent=1))
    (out / "alan-turing" / "arrived-late.json").write_text('{"leader_slug": "alan-turing"}')
    g = env["grades"] / "fable" / "alan-turing"
    (g / "arrived-late__fable__blinded__r0.json").write_text("{}")

    # A run that cannot see it: the shelf copy is hidden while normalize lists,
    # then restored before the prune. Simulated by pruning against a `kept` set
    # that predates its arrival.
    mod = load("normalize_transcripts")
    kept = {("ada-lovelace", "keynote-aaa"), ("ada-lovelace", "reupload-bbb"),
            ("alan-turing", "lecture-ccc")}
    report = mod.prune_orphans(out, kept, "blinded", env["grades"], 0.25,
                               shelf=env["src"], rejected=set())
    check("the late arrival survives, because its source is still on the shelf",
          (out / "alan-turing" / "arrived-late.json").exists(), f"report={report}")
    check("its grades are not orphaned",
          (g / "arrived-late__fable__blinded__r0.json").exists(),
          f"orphaned={[p.name for p in env['grades'].rglob('*.orphaned')]}")
    check("nothing was pruned at all this time", report["pruned"] == 0, f"report={report}")


# ---------------------------------------------------------------------------
# 7d. A refused prune must leave an honest log.
#
# FOUND BY ADVERSARIAL REVIEW. The guard raised before the log was written, so
# the log kept the previous cycle's success and the loop reported nothing.
# ---------------------------------------------------------------------------

def test_refusal_leaves_an_honest_log(tmp: Path) -> None:
    print("\n[7d] a refused prune says so in the log, and the loop notices")
    env = build(tmp)
    for i in range(20):
        (env["src"] / "ada-lovelace" / f"filler-{i:02d}.json").write_text(json.dumps({
            "leader_slug": "ada-lovelace", "source_id": f"filler-{i:02d}",
            "word_count": 50, "text": "[00:00:01] Ada Lovelace of Analytical Engines. " * 20,
        }, indent=1))
    out = tmp / "blind"
    normalize(env, out, tmp, extra=["--grades", str(env["grades"])])
    log = tmp / "normalize_blinded.json"
    log.write_text(json.dumps({"summary": {"marker": "PREVIOUS CYCLE"}}))

    empty = tmp / "empty"; empty.mkdir()
    r = subprocess.run(
        [PY, str(REPO / "scripts" / "normalize_transcripts.py"),
         "--transcripts", str(empty), "--out", str(out), "--roster", str(env["roster"]),
         "--mode", "blinded", "--grades", str(env["grades"]), "--log", str(log)],
        capture_output=True, text=True, cwd=REPO)
    check("normalize still exits non-zero", r.returncode != 0, f"rc={r.returncode}")
    written = json.loads(log.read_text())
    check("the log no longer claims the previous cycle's success",
          written["summary"].get("marker") != "PREVIOUS CYCLE", f"log={written}")
    check("the log records the refusal and what it would have removed",
          written["summary"].get("prune", {}).get("refused") is True
          and written["summary"]["prune"]["would_have_pruned"] == 23,
          f"prune={written['summary'].get('prune')}")

    loop = " ".join(commands("grade_loop.sh"))
    check("grade_loop.sh checks whether normalize succeeded",
          "NORMALIZE FAILED" in loop, "the loop ignores normalize's exit status")


# ---------------------------------------------------------------------------
# 8. Live corpus scan. Opt-in, because it reads data/ and costs a minute.
#
# This is the detector that found the bug in the first place: no two graded
# transcripts of one leader may score at or above the duplicate threshold.
# ---------------------------------------------------------------------------

def test_live_corpus_has_no_duplicates() -> None:
    print("\n[8] the live graded corpus holds no duplicate appearances")
    if os.environ.get("DEDUPE_SCAN") != "1":
        print("  SKIP  set DEDUPE_SCAN=1 to scan data/transcripts_blind")
        return
    blind = REPO / "data" / "transcripts_blind"
    if not blind.exists():
        print("  SKIP  no data/transcripts_blind in this clone")
        return
    d = load("dedupe_transcripts")
    from itertools import combinations
    hits = []
    for slug, recs in sorted(d.load(blind).items()):
        sh = [(r, d.shingles(r["text"])) for r in recs]
        for (a, sa), (b, sb) in combinations(sh, 2):
            if not sa or not sb:
                continue
            c = d.containment(sa, sb)
            if c >= d.DUP_THRESHOLD:
                hits.append(f"{slug}: {a['source_id']} ~ {b['source_id']} ({c:.3f})")
    check(f"no duplicate pair among the graded transcripts (checked {blind})",
          not hits, f"{len(hits)} pairs:\n          " + "\n          ".join(hits[:12]))


# ---------------------------------------------------------------------------
# 9. The sweep must orphan grades from the directory it was given.
#
# dedupe_transcripts.py takes --youtube for the corpus but read grades from a
# hardcoded "data/grades", relative to whatever the working directory happened
# to be. Run against any other corpus it silently orphaned nothing, or worse,
# the wrong repository's grades. This path now runs on every grading cycle, so
# it has to address the right directory.
# ---------------------------------------------------------------------------

def test_sweep_orphans_the_grades_it_was_given(tmp: Path) -> None:
    print("\n[9] the sweep orphans grades where it was told to look")
    corpus = tmp / "corpus" / "ada-lovelace"
    corpus.mkdir(parents=True)
    body = "[00:00:01] the analytical engine weaves algebraic patterns as the loom weaves flowers. " * 40
    for sid, extra in (("original-zzz", ""), ("reupload-zzz", "and one extra clause here. ")):
        (corpus / f"{sid}.json").write_text(json.dumps({
            "leader_slug": "ada-lovelace", "source_id": sid, "text": body + extra,
            "word_count": len(body.split()), "n_timestamp_marks": 1 if sid == "original-zzz" else 0,
        }, indent=1))

    grades = tmp / "grades" / "astra" / "ada-lovelace"
    grades.mkdir(parents=True)
    for sid in ("original-zzz", "reupload-zzz"):
        (grades / f"{sid}__astra__blinded__r0.json").write_text("{}")

    r = subprocess.run(
        [PY, str(REPO / "scripts" / "dedupe_transcripts.py"), "--sweep",
         "--youtube", str(tmp / "corpus"), "--happyscribe", str(tmp / "none"),
         "--grades", str(tmp / "grades"), "--out", str(tmp / "dedupe.json")],
        capture_output=True, text=True, cwd=tmp)
    check("the sweep runs against an arbitrary corpus", r.returncode == 0, r.stderr[-400:])
    retired = [p.name for p in (tmp / "corpus").rglob("*.superseded")]
    check("it retires the weaker copy of the duplicate", len(retired) == 1, f"retired={retired}")
    orphaned = [p.name for p in (tmp / "grades").rglob("*.orphaned")]
    check("it orphans that copy's grades in the directory it was given",
          orphaned == ["reupload-zzz__astra__blinded__r0.json.orphaned"], f"orphaned={orphaned}")
    check("the surviving copy keeps its grades",
          (grades / "original-zzz__astra__blinded__r0.json").exists())


# ---------------------------------------------------------------------------
# 10. A source the sweep retired must not be fetched again.
#
# FOUND BY ADVERSARIAL REVIEW of a78baf5, and confirmed. The sweep renames a
# retired source to `<source_id>.json.superseded`. fetch_transcripts.fetch_one
# decides what to skip with `dest.exists()` on `<source_id>.json`, which that
# name does not satisfy, so the retired video was downloaded again on the next
# cycle and retired again on the one after. That is the 222 -> 214 churn the
# merge path already documents, on the sweep path, and it spends the YouTube
# caption allowance the fetcher calls the scarcest resource in the pipeline.
# a78baf5 made it worse by running the sweep every grading cycle.
# ---------------------------------------------------------------------------

def test_superseded_source_is_not_refetched(tmp: Path) -> None:
    print("\n[10] a retired source is not fetched all over again")
    f = load("fetch_transcripts")
    out = tmp / "corpus"
    (out / "ada-lovelace").mkdir(parents=True)
    src = {"leader_slug": "ada-lovelace", "source_id": "retired-vid", "video_id": "vid-B"}

    (out / "ada-lovelace" / "retired-vid.json.superseded").write_text("{}")
    r = f.fetch_one(src, out, min_words=100, force=False)
    check("the fetcher recognises a superseded source and does not re-download it",
          r["status"] in ("superseded", "cached"), f"status={r.get('status')} r={r}")

    # force must still override, so a deliberate re-fetch stays possible.
    (out / "ada-lovelace" / "kept-vid.json").write_text("{}")
    r = f.fetch_one({"leader_slug": "ada-lovelace", "source_id": "kept-vid",
                     "video_id": "vid-A"}, out, min_words=100, force=False)
    check("an ordinary cached source is still reported as cached", r["status"] == "cached",
          f"status={r.get('status')}")

    # A new status that no tally knows about is worse than no status: it makes
    # attempted, succeeded and failed stop adding up, and the progress line
    # reports the skip as a failure. The repo rule is a taxonomy, never a bare
    # count, so the summary has to name it.
    src_txt = (REPO / "scripts" / "fetch_transcripts.py").read_text()
    check("the run summary reports superseded skips as their own category",
          '"superseded":' in src_txt, "superseded results vanish from the summary")
    check("the progress line subtracts superseded skips from the failure count",
          "done - ok - sup" in src_txt, "done - ok would report the skip as failed")
    check("a superseded candidate does not count toward a leader's target",
          'if r["status"] in ("ok", "cached"):\n            got += 1' in src_txt,
          "got += 1 must not fire for a superseded result")


def main() -> int:
    print("pipeline duplicate guards")
    for fn in (test_retired_source_is_pruned, test_orphaned_grades_stop_counting,
               test_prune_is_scoped_to_its_own_mode, test_qa_rejected_transcript_is_pruned,
               test_mass_prune_refuses, test_sweep_orphans_the_grades_it_was_given,
               test_prune_rechecks_the_shelf, test_refusal_leaves_an_honest_log,
               test_superseded_source_is_not_refetched):
        with tempfile.TemporaryDirectory() as td:
            fn(Path(td))
    test_sweep_runs_before_grading()
    test_sweep_report_is_kept()
    test_only_one_loop_prunes()
    test_live_corpus_has_no_duplicates()
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
