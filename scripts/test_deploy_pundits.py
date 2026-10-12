#!/usr/bin/env python3
"""The pundits publication path: guarded like the other two sites, and it cannot reach them.

Pundits plan, P4c. scripts/deploy_pundits.sh renders verbatim-pundits.tonygwu.com
from the explicitly named pundits production checkout and publishes through
wrangler.pundits.toml. Every real `npx` here is a tripwire that records its
arguments and exits 93, so nothing is ever published by this test.

  DRY-RUN      renders site-pundits/index.html from the registered pundits checkout
               and publishes nothing
  SOURCE       leaders data, or no data revision, is refused before rendering
  STALE        a results.json built from fewer grade files than are on disk is refused
  TARGET       a non-dry run reaches only the tripwire, and names wrangler.pundits.toml
  LEADERS      the leaders deploy.sh still refuses the pundits checkout
  CONFIG       wrangler.pundits.toml names its own Worker, directory and domain
  REVISION     the page and site-pundits/revision.json carry the data revision,
               and revision.json is served no-store
  LIVE         a live page from a revision we do not descend from is refused, and
               a live page with no revision.json needs --first-revision-deploy
  CONFIRM      after a publish the live revision is read back and must equal ours

The live revision is read through VI_LIVE_REVISION_URL, a file:// URL here, so
no check in this file touches the network.

  .venv/bin/python scripts/test_deploy_pundits.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []
SCRIPTS = ("data_clone_workflow.py", "study_profile.py", "study_env.sh", "daemon_guard.sh",
           "deploy_source.sh", "deploy.sh", "deploy_pundits.sh", "build_site.py", "build_study_site.py",
           "aggregate.py", "atomicio.py", "site_theme.py", "grading_contract.py")


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def git(root: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if p.returncode:
        raise AssertionError(f"git {args}: {p.stderr}")
    return p.stdout.strip()


def data_checkout(path: Path, origin: str, study: str | None, grade_files: int, read_n: int) -> str:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "446441+tonygwu@users.noreply.github.com")
    git(path, "config", "user.name", "Fixture")
    git(path, "config", "remote.origin.url", f"git@github.com:tonygwu/{origin}.git")
    if study:
        (path / ".study").write_text(study + "\n")
    (path / ".gitignore").write_text(".daemon-clone\n")
    (path / ".daemon-clone").write_text("repo-9\n")
    # The daemon checkout carries verbatim.role=daemon since plan phase P4b.
    git(path, "config", "verbatim.role", "daemon")
    dims = [d["key"] for d in json.loads((REPO / "profiles/pundits.json").read_text())["scoring"]["dimensions"]]
    results = {"leaders": [{"rank": 1, "slug": "p1", "name": "Pat Undit", "role": "host", "status": "scored",
                            "n_transcripts": 6, "confidence": "high",
                            "blinded": {"overall": 55.0, "ci_low": 50.0, "ci_high": 60.0, **{d: 55.0 for d in dims}},
                            "open": {}, "halo": {}}],
               "unranked": [], "diagnostics": {"grades_used": grade_files, "grade_files_read": read_n},
               "transcripts": [{"leader_slug": "p1", "source_id": "s0", "mode": "blinded", "venue_type": "solo",
                                "cal_overall": 55.0}]}
    # The open transcript's public metadata, which the page's recordings list reads.
    (path / "transcripts_open/p1").mkdir(parents=True)
    (path / "transcripts_open/p1/s0.json").write_text(json.dumps(
        {"url": "https://www.youtube.com/watch?v=fixture1", "yt_title": "Fixture episode", "text": "SECRET TEXT"}))
    (path / "results.json").write_text(json.dumps(results))  # rewritten below with the grade digest
    (path / "results_audit.json").write_text("{}")
    (path / "roster").mkdir()
    (path / "roster/final.json").write_text(json.dumps({"roster": []}))
    (path / "logs").mkdir()
    (path / "logs/calibration.json").write_text("{}")
    for i in range(grade_files):
        g = path / "grades/fable/p1" / f"s{i}__fable__blinded__r0.json"
        g.parent.mkdir(parents=True, exist_ok=True)
        g.write_text(json.dumps({"grade": {}, "fixture": i}))
    # Not grades: a moved-aside grade and a run provenance record must not count.
    for extra in ("grades/_obsolete/fable/p1/s0.old.json", "grades/_provenance/abc.json", "grades/_raw/fable/p1/s0.txt"):
        e = path / extra
        e.parent.mkdir(parents=True, exist_ok=True)
        e.write_text("{}")
    import aggregate as A
    results["diagnostics"]["grade_files_sha256"] = A.grade_files_digest(A.load_grades(path / "grades"))
    (path / "results.json").write_text(json.dumps(results))
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "fixture")
    return git(path, "rev-parse", "HEAD")


def public_clone(parent: Path, leaders: Path, pundits: Path) -> Path:
    pub = parent / "repo-9"
    (pub / "scripts").mkdir(parents=True)
    git(pub, "init", "-q", "-b", "main")
    for name in SCRIPTS:
        if (REPO / "scripts" / name).exists():
            shutil.copy2(REPO / "scripts" / name, pub / "scripts" / name)
    shutil.copytree(REPO / "profiles", pub / "profiles")
    for name in ("wrangler.toml", "wrangler.pundits.toml"):
        if (REPO / name).exists():
            shutil.copy2(REPO / name, pub / name)
    (pub / ".venv/bin").mkdir(parents=True)
    (pub / ".venv/bin/python").symlink_to(sys.executable)
    (pub / "data").symlink_to(leaders, target_is_directory=True)
    (pub / "data-pundits").symlink_to(pundits, target_is_directory=True)
    git(pub, "config", "verbatim.productionData", str(leaders))
    git(pub, "config", "verbatim.pundits.productionData", str(pundits))
    return pub


def run(pub: Path, script: str, *args, bin_dir: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("STUDY", "DATA", "SITE_DIR", "RUN_MARKER_DIR")}
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return subprocess.run(["bash", str(pub / "scripts" / script), *map(str, args)], cwd=pub, env=env,
                          capture_output=True, text=True)


def main() -> int:
    print("pundits deploy path")
    if not (REPO / "scripts/deploy_pundits.sh").exists() or not (REPO / "wrangler.pundits.toml").exists():
        check("scripts/deploy_pundits.sh and wrangler.pundits.toml exist", False)
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1
    with tempfile.TemporaryDirectory(prefix="p4c-") as td:
        tmp = Path(td).resolve()
        leaders = tmp / "leaders-data"
        rev_l = data_checkout(leaders, "verbatim-index-data", None, 1, 1)
        pundits = tmp / "pundits-data"
        rev_old = data_checkout(pundits, "verbatim-pundits-data", "pundits", 2, 2)
        # A second commit, so the fixture has an older revision a live page can carry.
        (pundits / "README.md").write_text("fixture\n")
        git(pundits, "add", "README.md")
        git(pundits, "commit", "-q", "-m", "second")
        rev_p = git(pundits, "rev-parse", "HEAD")
        stale = tmp / "pundits-stale"
        pub = public_clone(tmp, leaders, pundits)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        record = tmp / "npx-args.txt"
        live_dir = tmp / "live"
        live_dir.mkdir()
        live = live_dir / "revision.json"
        live_page = live_dir / "index.html"
        # NPX_MODE picks the stub: the tripwire by default; "publish" plays a
        # deploy that worked (the live revision and page become ours); "noop" one
        # that exited 0 and changed nothing; "clobber" one where another render
        # (grade_loop.sh rewrites site-pundits/index.html every cycle, with no
        # revision stamp) replaced the page just before the upload.
        (bin_dir / "npx").write_text(
            f'#!/bin/sh\necho "$@" > "{record}"\n'
            f'case "$NPX_MODE" in\n'
            f'  publish) cp site-pundits/revision.json "{live}"; cp site-pundits/index.html "{live_page}"; exit 0 ;;\n'
            f'  clobber) echo "<html>a loop render</html>" > site-pundits/index.html;\n'
            f'           cp site-pundits/revision.json "{live}"; cp site-pundits/index.html "{live_page}"; exit 0 ;;\n'
            f'  noop) exit 0 ;;\n'
            f'esac\necho DEPLOY-TRIPWIRE >&2\nexit 93\n')
        (bin_dir / "npx").chmod(0o755)

        os.environ["VI_LIVE_REVISION_URL"] = live.as_uri()
        os.environ["VI_LIVE_PAGE_URL"] = live_page.as_uri()
        os.environ["LIVE_CONFIRM_ATTEMPTS"], os.environ["LIVE_CONFIRM_WAIT"] = "1", "0"
        os.environ.pop("NPX_MODE", None)
        live.write_text(json.dumps({"data_revision": rev_old}))

        print("\n[DRY-RUN]")
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--data-revision", rev_p, "--dry-run",
                bin_dir=bin_dir)
        page = pub / "site-pundits" / "index.html"
        check("a dry run from the registered pundits checkout succeeds", r.returncode == 0, r.stderr[-400:])
        check("it renders the pundits page", page.exists() and "Verbatim Pundits" in page.read_text())
        check("it says it published nothing, and never reached npx",
              "published nothing" in r.stdout and not record.exists(), r.stdout[-300:])
        check("the staleness count ignores _obsolete, _provenance and _raw", "covers all 2 grade files" in r.stdout,
              r.stdout[-300:])
        check("the leaders page was not written", not (pub / "site" / "index.html").exists())

        print("\n[REVISION]")
        text = page.read_text() if page.exists() else ""
        check("the page carries the full data revision in a meta tag",
              f'<meta name="verbatim:data-revision" content="{rev_p}">' in text)
        check("and its short form in the footer", f"data revision {rev_p[:12]}" in text)
        rj = pub / "site-pundits" / "revision.json"
        meta = json.loads(rj.read_text()) if rj.exists() else {}
        check("site-pundits/revision.json names the data revision", meta.get("data_revision") == rev_p, str(meta))
        committed = datetime.fromtimestamp(int(git(pundits, "show", "-s", "--format=%ct", rev_p)), timezone.utc)
        check("with the data date: the revision's commit time as a UTC date, never a clock",
              meta.get("data_date") == committed.date().isoformat(), f"{meta} vs {committed.date()}")
        check("and the 64-hex content fingerprint of what was rendered",
              isinstance(meta.get("content_sha256"), str) and len(meta["content_sha256"]) == 64, str(meta))
        # FOUND 2026-10-12 by review: owner mode renders the daemon's uncommitted
        # output, and the footer named the HEAD commit as if it reproduced the page.
        check("clean published inputs: revision.json says so, and the footer claims nothing more",
              meta.get("data_uncommitted") is False and "uncommitted" not in text, str(meta))
        cal = pundits / "logs/calibration.json"
        cal.write_text('{"edited": "after the commit"}')
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--data-revision", rev_p, "--dry-run",
                bin_dir=bin_dir)
        dirty_text = page.read_text() if page.exists() else ""
        dirty_meta = json.loads(rj.read_text()) if rj.exists() else {}
        git(pundits, "checkout", "--", "logs/calibration.json")
        check("uncommitted published inputs: the footer says the page includes them",
              r.returncode == 0 and f"data revision {rev_p[:12]}" in dirty_text
              and "plus uncommitted changes" in dirty_text, (r.stderr + dirty_text)[-400:])
        check("and revision.json records it", dirty_meta.get("data_uncommitted") is True, str(dirty_meta))
        # FOUND 2026-10-12 by the second review: a grading cycle's run record under
        # grades/_provenance changes no rendered byte, and the fingerprint skips it.
        prov = pundits / "grades/_provenance/abc.json"
        prov.write_text('{"run": "a later cycle"}')
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--data-revision", rev_p, "--dry-run",
                bin_dir=bin_dir)
        prov_meta = json.loads(rj.read_text()) if rj.exists() else {}
        git(pundits, "checkout", "--", "grades/_provenance/abc.json")
        check("a change only under an underscore directory (_provenance) is not an uncommitted input",
              r.returncode == 0 and prov_meta.get("data_uncommitted") is False, (r.stderr + str(prov_meta))[-300:])
        headers = pub / "site-pundits" / "_headers"
        htext = headers.read_text() if headers.exists() else ""
        check("site-pundits/_headers serves revision.json no-store",
              "/revision.json" in htext and "Cache-Control: no-store" in htext, htext)

        check("the page lists the recording, linked to its source",
              '<a href="https://www.youtube.com/watch?v=fixture1" rel="noopener">Fixture episode</a>' in text, text[-800:])
        check("and never the transcript text", "SECRET TEXT" not in text)

        print("\n[LIVE]")
        live.unlink()
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--data-revision", rev_p, "--dry-run",
                bin_dir=bin_dir)
        check("a live page with no revision.json is refused",
              r.returncode != 0 and "--first-revision-deploy" in r.stderr, r.stderr[-300:])
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--data-revision", rev_p, "--dry-run",
                "--first-revision-deploy", bin_dir=bin_dir)
        check("--first-revision-deploy lets that one through", r.returncode == 0, r.stderr[-300:])
        # FOUND 2026-10-12 by review: the flag turned ANY failure to read into a pass,
        # so an error page or a bot-filter answer in front of a newer live page would
        # have let an older render replace it.
        live.write_text("<html>error code: 1104</html>")
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--data-revision", rev_p, "--dry-run",
                "--first-revision-deploy", bin_dir=bin_dir)
        check("--first-revision-deploy does not cover a live revision.json that cannot be read",
              r.returncode != 0 and "cannot read" in r.stderr, r.stderr[-300:])
        # A newer revision that our checkout does not contain: made, then reset away.
        (pundits / "NEWER.md").write_text("newer\n")
        git(pundits, "add", "NEWER.md")
        git(pundits, "commit", "-q", "-m", "newer")
        newer = git(pundits, "rev-parse", "HEAD")
        git(pundits, "reset", "-q", "--hard", rev_p)
        live.write_text(json.dumps({"data_revision": newer}))
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--data-revision", rev_p, "--dry-run",
                bin_dir=bin_dir)
        check("a live page built from a revision we do not descend from is refused",
              r.returncode != 0 and "not an ancestor" in r.stderr, r.stderr[-300:])
        # FOUND 2026-10-12 by review: at the SAME data revision the ancestor check
        # always passes, so a render by older public code replaced a newer page.
        ident = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        git(pub, "add", "scripts", "profiles")
        git(pub, *ident, "commit", "-q", "-m", "public one")
        pub_one = git(pub, "rev-parse", "HEAD")
        (pub / "NEWER-CODE.md").write_text("newer\n")
        git(pub, "add", "NEWER-CODE.md")
        git(pub, *ident, "commit", "-q", "-m", "public two")
        pub_two = git(pub, "rev-parse", "HEAD")
        git(pub, "reset", "-q", "--hard", pub_one)
        live.write_text(json.dumps({"data_revision": rev_p, "public_revision": pub_two}))
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--data-revision", rev_p, "--dry-run",
                bin_dir=bin_dir)
        check("at the same data revision, a live page rendered by public code we lack is refused",
              r.returncode != 0 and "public" in r.stderr and pub_two[:12] in r.stderr, r.stderr[-300:])
        live.write_text(json.dumps({"data_revision": rev_p, "public_revision": pub_one}))
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--data-revision", rev_p, "--dry-run",
                bin_dir=bin_dir)
        check("and one rendered by the same public code passes", r.returncode == 0, r.stderr[-300:])
        live.write_text(json.dumps({"data_revision": rev_old}))

        print("\n[FINGERPRINT]")
        # FOUND 2026-10-12 by review: the page now reads transcripts_open for its
        # recordings list, and the fingerprint that binds a render to its inputs did
        # not cover it.
        def fp() -> str:
            return subprocess.run([sys.executable, "scripts/data_clone_workflow.py", "publication-source",
                                   "--production-data", str(pundits), "--data-revision", rev_p, "--site", "pundits",
                                   "--study", "pundits", "--fingerprint"], cwd=pub, capture_output=True, text=True).stdout.strip()
        before = fp()
        meta_files = sorted((pundits / "transcripts_open").rglob("*.json"))
        saved = meta_files[0].read_text() if meta_files else ""
        if meta_files:
            meta_files[0].write_text(saved.replace("Fixture episode", "Renamed episode"))
        after = fp()
        if meta_files:
            meta_files[0].write_text(saved)
        check("a change under transcripts_open changes the publication fingerprint",
              bool(meta_files) and len(before) == 64 and before != after, f"{before!r} {after!r}")

        print("\n[SOURCE]")
        r = run(pub, "deploy_pundits.sh", "--production-data", leaders, "--data-revision", rev_l, "--dry-run",
                bin_dir=bin_dir)
        check("leaders data is refused", r.returncode != 0 and "REFUSING" in r.stderr, r.stderr[-300:])
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--dry-run", bin_dir=bin_dir)
        check("a missing data revision is refused", r.returncode != 0 and "REFUSING" in r.stderr, r.stderr[-300:])

        print("\n[STALE]")
        git(pub, "config", "verbatim.pundits.productionData", str(stale))
        rev_s = data_checkout(stale, "verbatim-pundits-data", "pundits", 3, 1)
        (pub / "data-pundits").unlink()
        (pub / "data-pundits").symlink_to(stale, target_is_directory=True)
        r = run(pub, "deploy_pundits.sh", "--production-data", stale, "--data-revision", rev_s, "--dry-run",
                bin_dir=bin_dir)
        check("a stale aggregate is refused", r.returncode != 0 and "stale" in (r.stdout + r.stderr).lower(),
              (r.stdout + r.stderr)[-300:])
        git(pub, "config", "verbatim.pundits.productionData", str(pundits))
        (pub / "data-pundits").unlink()
        (pub / "data-pundits").symlink_to(pundits, target_is_directory=True)
        # FOUND 2026-10-12 by the second review (in the gate report; the deploy had the
        # same check): grade.py --force moves the old grade aside and writes a new one,
        # so the file count matches while results.json describes other bytes.
        regraded = pundits / "grades/fable/p1/s0__fable__blinded__r0.json"
        old_bytes = regraded.read_text()
        regraded.write_text(json.dumps({"grade": {"rescored": True}, "fixture": 0}))
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--data-revision", rev_p, "--dry-run",
                bin_dir=bin_dir)
        regraded.write_text(old_bytes)
        check("a forced re-grade (same count, new bytes) is refused as stale",
              r.returncode != 0 and "grade_files_sha256" in (r.stdout + r.stderr), (r.stdout + r.stderr)[-300:])

        print("\n[TARGET]")
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--data-revision", rev_p, bin_dir=bin_dir)
        args = record.read_text().strip() if record.exists() else ""
        check("a non-dry run reaches only the tripwire", r.returncode != 0 and "DEPLOY-TRIPWIRE" in r.stderr,
              f"rc={r.returncode} {r.stderr[-200:]}")
        check("and names wrangler.pundits.toml", args == "wrangler deploy -c wrangler.pundits.toml", args)

        print("\n[CONFIRM]")
        os.environ["NPX_MODE"] = "publish"
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--data-revision", rev_p, bin_dir=bin_dir)
        check("a publish whose live revision reads back as ours succeeds and says so",
              r.returncode == 0 and f"live page confirmed at data revision {rev_p[:12]}" in r.stdout,
              f"rc={r.returncode} {r.stdout[-300:]} {r.stderr[-300:]}")
        live.write_text(json.dumps({"data_revision": rev_old}))
        os.environ["NPX_MODE"] = "noop"
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--data-revision", rev_p, bin_dir=bin_dir)
        check("a publish whose live page still serves the old revision fails loudly",
              r.returncode != 0 and rev_old[:12] in r.stderr, f"rc={r.returncode} {r.stderr[-300:]}")
        # FOUND 2026-10-12 by review: an earlier page at the SAME data revision read
        # back as a success, because only data_revision was compared. The daemon
        # renders uncommitted output, so the same revision can carry other content.
        live.write_text(json.dumps({"data_revision": rev_p, "content_sha256": "0" * 64}))
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--data-revision", rev_p, bin_dir=bin_dir)
        check("an earlier page at the same data revision is not taken for this publish",
              r.returncode != 0 and "content_sha256" in r.stderr, f"rc={r.returncode} {r.stderr[-300:]}")
        os.environ["NPX_MODE"] = "clobber"
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--data-revision", rev_p, bin_dir=bin_dir)
        check("a page replaced by another render before the upload fails the confirm, naming the page",
              r.returncode != 0 and "page" in r.stderr and "data-revision" in r.stderr,
              f"rc={r.returncode} {r.stderr[-300:]}")
        os.environ.pop("NPX_MODE", None)

        print("\n[LEADERS]")
        r = run(pub, "deploy.sh", "--production-data", pundits, "--data-revision", rev_p, "--dry-run",
                bin_dir=bin_dir)
        check("the leaders deploy.sh refuses the pundits checkout",
              r.returncode != 0 and "REFUSING" in r.stderr, r.stderr[-300:])

    print("\n[CONFIG]")
    cfg = (REPO / "wrangler.pundits.toml").read_text()
    lead = (REPO / "wrangler.toml").read_text()
    check("its Worker is verbatim-pundits", 'name = "verbatim-pundits"' in cfg)
    check("its assets directory is ./site-pundits", 'directory = "./site-pundits"' in cfg)
    check("its route is verbatim-pundits.tonygwu.com", 'pattern = "verbatim-pundits.tonygwu.com"' in cfg)
    check("it shares no Worker name or route with the leaders config",
          'name = "verbatim-index"' not in cfg and "verbatim-index.tonygwu.com" not in cfg and "verbatim-pundits" not in lead)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
