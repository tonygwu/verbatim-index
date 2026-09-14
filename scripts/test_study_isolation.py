#!/usr/bin/env python3
"""Two studies share this engine, and one must never touch the other's data.

Pundits plan, P1. Every check here runs the REAL script or function against two
temporary git checkouts, one leaders and one pundits, and asserts both the
refusal and that the leaders tree is byte-identical afterwards. Nothing reads or
writes the live data, and nothing can reach a judge: grade.py runs with a PATH
whose claude, codex and agy are tripwires.

  ISOLATION-RULE   study_profile.check_path: leaders accepts its unmarked tree,
                   pundits refuses it, leaders refuses a pundits tree, and
                   pundits refuses a marked tree whose origin is not its repo.
  NORMALIZE        a pundits normalize whose --grades names the leaders tree
                   refuses and orphans nothing; the same run inside the pundits
                   tree succeeds, so the refusal is about the path.
  QA / AGGREGATE   pundits QA and aggregate given leaders inputs refuse.
  GRADE            pundits grade.py given a leaders --out refuses before any
                   judge binary runs.
  DEDUPE-DEFAULTS  pundits dedupe with NO path flags writes only in the
                   pundits tree, which is how happyscribe_loop.sh calls it.
  HS-DEFAULTS      pundits fetch_happyscribe with NO path flags reads the
                   pundits roster and candidate pool.
  WITHDRAW         ownership and retirement resolve through the study's link;
                   a pundits link pointing at leaders data is refused.
  DAEMON-GUARD     a pundits loop starts only on a pundits checkout, a leaders
                   loop refuses a pundits checkout, and the legacy leaders start
                   still works.
  MARKERS          each study's run markers live under its own data, and a
                   pundits fetcher is not seen as running by a leaders reader.
  PUBLICATION      the pundits production source resolves through its own
                   config key, refuses leaders data, and fingerprints its own
                   shelves; an unknown site is refused.

  .venv/bin/python scripts/test_study_isolation.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PY = sys.executable
PASS, FAIL = [], []
LEAK_ENV = ("STUDY", "DATA", "SITE_DIR", "RUN_MARKER_DIR")


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def run(argv, cwd=None, env=None, path_prefix=None) -> subprocess.CompletedProcess:
    base = {k: v for k, v in os.environ.items() if k not in LEAK_ENV}
    base.update(env or {})
    if path_prefix:
        base["PATH"] = f"{path_prefix}{os.pathsep}{base['PATH']}"
    return subprocess.run([str(a) for a in argv], cwd=cwd, env=base, capture_output=True, text=True)


def git(root: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if p.returncode:
        raise AssertionError(f"git {args}: {p.stderr}")
    return p.stdout.strip()


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if ".git" in rel.parts or not p.is_file():
            continue
        h.update(f"{rel}\0".encode() + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


def checkout(path: Path, origin: str, slug: str, name: str, study: str | None) -> str:
    """A committed data checkout with one person, one transcript and one grade."""
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "446441+tonygwu@users.noreply.github.com")
    git(path, "config", "user.name", "Fixture")
    git(path, "config", "remote.origin.url", f"git@github.com:tonygwu/{origin}.git")
    if study:
        (path / ".study").write_text(study + "\n")
    (path / ".daemon-clone").write_text("repo-9\n")
    write_json(path / "roster/final.json",
               {"roster": [{"slug": slug, "name": name, "company": "Acme Show", "role": "host", "sector": "s"}]})
    rec = {"leader_slug": slug, "source_id": "a", "text": "we talked about many things today " * 40,
           "word_count": 240}
    for shelf in ("transcripts", "transcripts_blind"):
        write_json(path / shelf / slug / "a.json", rec)
    (path / "transcripts_hs").mkdir()
    write_json(path / "grades/fable" / slug / "a__fable__blinded__r0.json",
               {"judge": "fable", "mode": "blinded", "leader_slug": slug, "source_id": "a"})
    write_json(path / "sources/happyscribe_candidates.json", {"someone-else": []})
    (path / "logs").mkdir()
    (path / "logs/.keep").write_text("")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "fixture")
    return git(path, "rev-parse", "HEAD")


def public_clone(parent: Path, links: dict[str, Path], name: str = "repo-9") -> Path:
    """A public clone, repo-9 by default, carrying the study files and the given data links."""
    pub = parent / name
    (pub / "scripts").mkdir(parents=True)
    git(pub, "init", "-q", "-b", "main")
    shutil.copytree(REPO / "profiles", pub / "profiles") if (REPO / "profiles").is_dir() else None
    for name in ("daemon_guard.sh", "study_env.sh", "run_marker.sh"):
        if (REPO / "scripts" / name).exists():
            shutil.copy2(REPO / "scripts" / name, pub / "scripts" / name)
    for link, target in links.items():
        (pub / link).symlink_to(target, target_is_directory=True)
    return pub


def test_rule(L: Path, P: Path, wrong: Path) -> None:
    print("\n[ISOLATION-RULE] study_profile.check_path")
    try:
        import study_profile as SP
    except Exception as exc:
        check("study_profile is importable", False, repr(exc))
        return

    def refuses(path, study, needle):
        try:
            SP.check_path(path, study)
        except RuntimeError as exc:
            return needle in str(exc)
        return False

    try:
        SP.check_path(L / "grades", "leaders")
        ok = True
    except RuntimeError:
        ok = False
    check("leaders accepts its unmarked legacy tree", ok)
    check("pundits refuses the unmarked leaders tree", refuses(L / "grades", "pundits", ".study"))
    check("leaders refuses a tree whose .study names pundits", refuses(P / "grades", "leaders", "pundits"))
    try:
        SP.check_path(P / "grades" / "not-yet-created", "pundits")
        ok = True
    except RuntimeError:
        ok = False
    check("pundits accepts its own tree, including a path not created yet", ok)
    check("pundits refuses a marked tree whose origin is another repository",
          refuses(wrong / "grades", "pundits", "origin"))
    check("an unknown study is refused, not defaulted", refuses(L, "no-such-study", "unknown study"))


def test_scripts(L: Path, P: Path, tmp: Path) -> None:
    print("\n[NORMALIZE / QA / AGGREGATE / GRADE] a pundits run given leaders paths")
    s = REPO / "scripts"
    before = tree_hash(L)
    r = run([PY, s / "normalize_transcripts.py", "--study", "pundits", "--mode", "blinded",
             "--transcripts", P / "transcripts", "--out", P / "transcripts_blind",
             "--roster", P / "roster/final.json", "--log", P / "logs/normalize.json",
             "--grades", L / "grades"])
    check("NORMALIZE: --grades on the leaders tree is refused",
          r.returncode != 0 and "REFUSING" in r.stderr, r.stderr[-300:])
    check("NORMALIZE: and the leaders tree is unchanged", tree_hash(L) == before)
    r = run([PY, s / "normalize_transcripts.py", "--study", "pundits", "--mode", "blinded",
             "--transcripts", P / "transcripts", "--out", P / "transcripts_blind",
             "--roster", P / "roster/final.json", "--log", P / "logs/normalize.json",
             "--grades", P / "grades"])
    check("NORMALIZE: the same run inside the pundits tree succeeds", r.returncode == 0, r.stderr[-300:])

    r = run([PY, s / "qa_transcripts.py", "--study", "pundits", "--transcripts", L / "transcripts",
             "--roster", P / "roster/final.json", "--out", P / "logs/qa.json"])
    check("QA: leaders transcripts are refused", r.returncode != 0 and "REFUSING" in r.stderr, r.stderr[-300:])

    r = run([PY, s / "aggregate.py", "--study", "pundits", "--grades", L / "grades",
             "--roster", P / "roster/final.json", "--out", P / "results.json"])
    check("AGGREGATE: leaders grades are refused", r.returncode != 0 and "REFUSING" in r.stderr, r.stderr[-300:])
    check("AGGREGATE: and nothing was written", not (P / "results.json").exists())

    bin_dir = tmp / "tripwire-bin"
    bin_dir.mkdir()
    for name in ("claude", "codex", "agy", "cl"):
        (bin_dir / name).write_text("#!/bin/sh\necho JUDGE-TRIPWIRE >&2\nexit 93\n")
        (bin_dir / name).chmod(0o755)
    r = run([PY, s / "grade.py", "--study", "pundits", "--transcripts", P / "transcripts_blind",
             "--roster", P / "roster/final.json", "--out", L / "grades",
             "--errors", P / "logs/grade_errors.jsonl", "--judges", "fable", "--modes", "blinded",
             "--fable-accounts", "default"], path_prefix=bin_dir)
    check("GRADE: a leaders --out is refused", r.returncode != 0 and "REFUSING" in r.stderr, r.stderr[-300:])
    check("GRADE: no judge binary ran", "JUDGE-TRIPWIRE" not in r.stdout + r.stderr)
    check("GRADE: and the leaders tree is unchanged", tree_hash(L) == before)


def test_defaults(L: Path, P: Path, tmp: Path) -> None:
    print("\n[DEDUPE-DEFAULTS / HS-DEFAULTS] no path flags, the study decides")
    pub = public_clone(tmp / "defaults", {"data": L, "data-pundits": P})
    before = tree_hash(L)
    s = REPO / "scripts"
    r = run([PY, s / "dedupe_transcripts.py", "--study", "pundits", "--sweep"], cwd=pub)
    check("DEDUPE-DEFAULTS: the sweep runs", r.returncode == 0, r.stderr[-300:])
    check("DEDUPE-DEFAULTS: its report lands in the pundits tree", (P / "logs/dedupe.json").exists())
    check("DEDUPE-DEFAULTS: the leaders tree is unchanged", tree_hash(L) == before)

    r = run([PY, s / "fetch_happyscribe.py", "--study", "pundits", "--report-unsearched"], cwd=pub)
    check("HS-DEFAULTS: reads the pundits roster and pool",
          r.returncode == 0 and r.stdout.strip() == "pundit-p", f"rc={r.returncode} out={r.stdout!r} {r.stderr[-200:]}")
    check("HS-DEFAULTS: the leaders tree is unchanged", tree_hash(L) == before)


def test_withdraw(L: Path, P: Path, tmp: Path) -> None:
    print("\n[WITHDRAW] ownership and shelves resolve through the study's link")
    spec = importlib.util.spec_from_file_location("ws_iso", REPO / "scripts" / "withdraw_sources.py")
    ws = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ws)
    good = public_clone(tmp / "w-good", {"data": L, "data-pundits": P})
    bad = public_clone(tmp / "w-bad", {"data": L, "data-pundits": L})
    before = tree_hash(L)
    try:
        why_good = ws.require_daemon_clone(good, study="pundits")
        why_bad = ws.require_daemon_clone(bad, study="pundits")
        res = ws.retire(good, "leader-x", "a", True, study="pundits")
    except TypeError as exc:
        check("WITHDRAW: functions take a study", False, repr(exc))
        return
    check("WITHDRAW: the owner check passes on the pundits checkout", why_good is None, str(why_good))
    check("WITHDRAW: a pundits link pointing at leaders data is refused",
          why_bad is not None and ".study" in why_bad, str(why_bad))
    check("WITHDRAW: retiring a leaders recording under pundits finds nothing",
          res.get("status") == "failed", str(res))
    check("WITHDRAW: and the leaders tree is unchanged", tree_hash(L) == before)


def guard_rc(pub: Path, study: str | None) -> subprocess.CompletedProcess:
    env = {"STUDY": study} if study else {}
    return run(["bash", "-c", ". scripts/study_env.sh && . scripts/daemon_guard.sh && require_daemon_clone"],
               cwd=pub, env=env)


def test_daemon_guard(L: Path, P: Path, tmp: Path) -> None:
    print("\n[DAEMON-GUARD] a loop starts only on its own study's checkout")
    if not (REPO / "scripts/study_env.sh").exists():
        check("DAEMON-GUARD: scripts/study_env.sh exists", False)
        return
    r = guard_rc(public_clone(tmp / "g1", {"data": L, "data-pundits": P}), "pundits")
    check("a pundits loop starts on the pundits checkout", r.returncode == 0, r.stderr[-300:])
    r = guard_rc(public_clone(tmp / "g2", {"data": L, "data-pundits": L}), "pundits")
    check("a pundits loop refuses a link to leaders data", r.returncode != 0 and ".study" in r.stderr, r.stderr[-300:])
    r = guard_rc(public_clone(tmp / "g3", {"data": P}), None)
    check("a leaders loop refuses a pundits checkout", r.returncode != 0 and "pundits" in r.stderr, r.stderr[-300:])
    r = guard_rc(public_clone(tmp / "g4", {"data": L}), None)
    check("the legacy leaders start still works", r.returncode == 0, r.stderr[-300:])
    r = guard_rc(public_clone(tmp / "g5", {"data": L}), "no-such-study")
    check("an unknown STUDY is refused", r.returncode != 0 and "unknown study" in r.stderr, r.stderr[-300:])


def test_markers(L: Path, P: Path, tmp: Path) -> None:
    print("\n[MARKERS] run markers belong to one study")
    if not (REPO / "scripts/study_env.sh").exists():
        check("MARKERS: scripts/study_env.sh exists", False)
        return
    pub = public_clone(tmp / "m", {"data": L, "data-pundits": P})
    env_of = lambda study: run(["bash", "-c", '. scripts/study_env.sh && printf %s "$RUN_MARKER_DIR"'],
                               cwd=pub, env={"STUDY": study} if study else {}).stdout
    check("a pundits loop's markers live under data-pundits", env_of("pundits") == "data-pundits/logs/running")
    check("a leaders loop's markers stay under data", env_of(None) == "data/logs/running")
    holder = subprocess.Popen(
        ["bash", "-c", '. scripts/study_env.sh && . scripts/run_marker.sh && '
                       'claim_run_marker fetch_loop.sh && sleep 30'],
        cwd=pub, env={**{k: v for k, v in os.environ.items() if k not in LEAK_ENV}, "STUDY": "pundits"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if (P / "logs/running/fetch_loop.sh.marker").exists():
                break
            time.sleep(0.1)
        ask = '. scripts/study_env.sh && . scripts/run_marker.sh; run_marker_alive fetch_loop.sh; echo "rc=$?"'
        check("the pundits reader sees the pundits fetcher", "rc=0" in run(["bash", "-c", ask], cwd=pub,
                                                                         env={"STUDY": "pundits"}).stdout)
        check("a leaders reader does not", "rc=1" in run(["bash", "-c", ask], cwd=pub).stdout)
        check("no marker directory appeared in the leaders tree", not (L / "logs/running").exists())
    finally:
        holder.terminate()
        holder.wait(timeout=5)


def test_publication(L: Path, P: Path, rev_l: str, rev_p: str, tmp: Path) -> None:
    print("\n[PUBLICATION] each study publishes only its own production source")
    import data_clone_workflow as D
    pub = public_clone(tmp / "pubsrc", {"data": L, "data-pundits": P})
    git(pub, "config", "verbatim.productionData", str(L))
    git(pub, "config", "verbatim.pundits.productionData", str(P))
    try:
        check("the leaders production path is unchanged", D.production_path(pub) == L.resolve())
        check("the pundits production path uses its own key", D.production_path(pub, "pundits") == P.resolve())
        try:
            D.publication_source(pub, L, rev_l, "pundits")
            refused = False
        except RuntimeError:
            refused = True
        check("a pundits publication of leaders data is refused", refused)
        check("a pundits publication of its own checkout is accepted",
              D.publication_source(pub, P, rev_p, "pundits") == P.resolve())
        check("leaders publication still works", D.publication_source(pub, L, rev_l) == L.resolve())
        check("the pundits site fingerprints its own shelves", len(D.fingerprint(P, "pundits")) == 64)
        try:
            D.fingerprint(P, "no-such-site")
            unknown = False
        except (RuntimeError, ValueError):
            unknown = True
        check("an unknown site is refused rather than treated as predictions", unknown)
        # With NO pundits production registered, the study's own link is still
        # treated as production: the owner may aggregate into it, anyone else
        # may not.
        owner = public_clone(tmp / "agg-owner", {"data-pundits": P})
        other = public_clone(tmp / "agg-other", {"data-pundits": P}, name="repo-8")
        try:
            D.guard_aggregate(owner, P / "results.json", "pundits")
            owner_ok = True
        except RuntimeError as exc:
            owner_ok = False
            print(f"        {exc}")
        check("an unregistered study's owner may aggregate into its own link", owner_ok)
        try:
            D.guard_aggregate(other, P / "results.json", "pundits")
            other_refused = False
        except RuntimeError as exc:
            other_refused = "repo-9" in str(exc)
        check("and another clone may not", other_refused)
    except TypeError as exc:
        check("PUBLICATION: functions take a study", False, repr(exc))


def test_gitignore(tmp: Path) -> None:
    print("\n[GITIGNORE] the pundits data link and site build never enter the public repo")
    probe = tmp / "ignore-probe"
    probe.mkdir()
    git(probe, "init", "-q")
    (probe / ".gitignore").write_text((REPO / ".gitignore").read_text())
    target = tmp / "ignore-target"
    target.mkdir()
    (probe / "data-pundits").symlink_to(target, target_is_directory=True)
    (probe / "site-pundits").mkdir()
    (probe / "site-pundits/index.html").write_text("x")
    for rel in ("data-pundits", "site-pundits/index.html"):
        r = subprocess.run(["git", "-C", str(probe), "check-ignore", "-q", rel])
        check(f"{rel} is ignored", r.returncode == 0)


def main() -> int:
    print("study isolation")
    with tempfile.TemporaryDirectory(prefix="study-iso-") as td:
        tmp = Path(td).resolve()
        L = tmp / "leaders-data"
        P = tmp / "pundits-data"
        wrong = tmp / "wrong-origin"
        rev_l = checkout(L, "verbatim-index-data", "leader-x", "Lee Der", None)
        rev_p = checkout(P, "verbatim-pundits-data", "pundit-p", "Pat Undit", "pundits")
        checkout(wrong, "verbatim-index-data", "pundit-w", "Wren Ong", "pundits")
        test_rule(L, P, wrong)
        test_scripts(L, P, tmp)
        test_defaults(L, P, tmp)
        test_withdraw(L, P, tmp)
        test_daemon_guard(L, P, tmp)
        test_markers(L, P, tmp)
        test_publication(L, P, rev_l, rev_p, tmp)
        test_gitignore(tmp)
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
