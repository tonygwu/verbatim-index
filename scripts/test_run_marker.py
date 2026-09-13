#!/usr/bin/env python3
"""A transcript source announces that it is running with a marker file.

WHY THIS EXISTS. grade_loop.sh must not declare grading finished while a
transcript source is still adding transcripts. It used to decide that by
reading the process list for a shell running a script named in FETCHERS. On
2026-09-11 that read answered "no source is running" at 07:49:51Z while
happyscribe_loop kept running until 08:24:33Z. The same function answered
correctly on every later bench test, so the cause was never found. Process
text was the wrong evidence: it is a guess about identity, made by parsing.

Now each fetch loop CLAIMS a marker when it starts and removes it when it
exits, and the grader asks the marker. Measured on this Mac's /bin/bash 3.2
before writing this: the EXIT trap runs on a normal exit and on a plain
`kill` (SIGTERM), and does NOT run on `kill -9`. So a marker can outlive its
loop, and "the file exists" is not enough on its own. The marker records the
loop's pid and its start time, and it counts only while that pid is alive AND
still has that start time. The start time is read with TZ=UTC, because `ps`
prints it in local time otherwise and the writer and reader could disagree.
File mtime is never consulted.

What is asserted here, against real processes:

  NONE       no marker means no source is running.
  CLAIM      a claiming loop is seen as running while it runs.
  EXIT       a normal exit removes the marker.
  TERM       a plain `kill` removes the marker.
  KILL9      after `kill -9` the marker stays, is NOT counted, and the reader
             says so on stderr instead of staying quiet.
  REUSED     a marker whose pid now belongs to a different process is NOT
             counted. Pids get reused; the start time tells them apart.
  MENTION    a process whose command line merely names the script, with no
             marker, is NOT counted. This was the pgrep hazard.
  DUPLICATE  a second claim while the first loop is alive is refused, and the
             first loop's marker is left intact.
  FOREIGN    a process that did not write the marker cannot remove it.
  MALFORMED  an unreadable marker is an error (status 2), never a guess.
  NO_MTIME   the helper never reads file modification time.
  WIRED      both fetch loops claim, grade_loop asks, grade_loop stops loudly
             on a malformed marker, and data/.gitignore ignores the markers.

  .venv/bin/python scripts/test_run_marker.py
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HELPER = REPO / "scripts" / "run_marker.sh"
NAME = "zz_fake_loop.sh"
PASS, FAIL = [], []
STARTED: list[subprocess.Popen] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if not cond and detail else ""))


def env(tmp: Path) -> dict:
    return {**os.environ, "RUN_MARKER_DIR": str(tmp / "running")}


def ask(tmp: Path) -> tuple[int, str]:
    r = subprocess.run(["bash", "-c", f'. "{HELPER}"; run_marker_alive "{NAME}"'],
                       capture_output=True, text=True, env=env(tmp))
    return r.returncode, r.stderr


def marker(tmp: Path) -> Path:
    return tmp / "running" / f"{NAME}.marker"


def start_loop(tmp: Path, body: str = "sleep 30") -> subprocess.Popen:
    script = tmp / f"loop_{len(STARTED)}.sh"
    script.write_text(f'. "{HELPER}"\nclaim_run_marker "{NAME}" || exit 3\n{body}\n')
    p = subprocess.Popen(["bash", str(script)], env=env(tmp), start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    STARTED.append(p)
    return p


def wait_for(cond, timeout: float = 5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return cond()


def main() -> int:
    print("run marker")
    check("scripts/run_marker.sh exists", HELPER.exists(),
          "no helper; the grader still has nothing but process text to go on")
    if HELPER.exists():
        behaviour()
    else:
        print("  (behaviour checks skipped: nothing to run them against)")
    wiring()
    return finish()


def behaviour() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        print("\nNONE")
        rc, _ = ask(tmp)
        check("no marker: not running (status 1)", rc == 1, f"status {rc}")

        print("\nCLAIM / EXIT")
        a = start_loop(tmp, body="sleep 1.5")
        check("the marker appears when a loop claims it", wait_for(lambda: marker(tmp).exists()))
        rc, err = ask(tmp)
        check("a claiming loop is seen as running (status 0)", rc == 0, f"status {rc}: {err}")
        text = marker(tmp).read_text() if marker(tmp).exists() else ""
        check("the marker records the loop's pid", f"pid={a.pid}" in text, text)
        check("the marker records a start time", re.search(r"^started_utc=\S", text, re.M) is not None, text)
        a.wait(timeout=10)
        check("a normal exit removes the marker", wait_for(lambda: not marker(tmp).exists()))
        rc, _ = ask(tmp)
        check("after a normal exit: not running", rc == 1, f"status {rc}")

        print("\nTERM")
        b = start_loop(tmp)
        wait_for(lambda: marker(tmp).exists())
        os.kill(b.pid, signal.SIGTERM)
        check("a plain kill removes the marker", wait_for(lambda: not marker(tmp).exists()),
              "SIGTERM left the marker behind")

        print("\nKILL9")
        c = start_loop(tmp)
        wait_for(lambda: marker(tmp).exists())
        os.kill(c.pid, signal.SIGKILL)
        c.wait(timeout=10)
        check("kill -9 leaves the marker behind (the case the pid check exists for)",
              marker(tmp).exists(), "the marker vanished, so this case did not reproduce")
        rc, err = ask(tmp)
        check("a marker whose loop is dead is NOT counted", rc == 1, f"status {rc}")
        check("and the reader says so on stderr", NAME in err and err.strip() != "", repr(err))
        marker(tmp).unlink(missing_ok=True)

        print("\nREUSED")
        other = subprocess.Popen(["sleep", "30"], start_new_session=True)
        STARTED.append(other)
        (tmp / "running").mkdir(exist_ok=True)
        marker(tmp).write_text(f"pid={other.pid}\nstarted_utc=Thu Jan  1 00:00:00 1970\n")
        rc, err = ask(tmp)
        check("a live pid with a different start time is NOT counted", rc == 1, f"status {rc}: {err}")
        marker(tmp).unlink(missing_ok=True)

        print("\nMENTION")
        m = subprocess.Popen(["bash", "-c", f": mentions {NAME}; sleep 30"], start_new_session=True)
        STARTED.append(m)
        time.sleep(0.5)
        naive = subprocess.run(["pgrep", "-f", NAME], capture_output=True).returncode == 0
        check("pgrep -f does match the mention (so this case really reproduces)", naive)
        rc, _ = ask(tmp)
        check("a mention with no marker is NOT counted", rc == 1, f"status {rc}")

        print("\nDUPLICATE / FOREIGN")
        d1 = start_loop(tmp)
        wait_for(lambda: marker(tmp).exists())
        d2 = start_loop(tmp)
        try:
            d2.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        check("a second claim while the first loop is alive is refused",
              d2.returncode == 3, f"second loop status {d2.returncode}")
        check("the refusal says why", "running" in (d2.stderr.read() if d2.stderr else ""))
        still = marker(tmp).read_text() if marker(tmp).exists() else ""
        check("the first loop's marker is intact", f"pid={d1.pid}" in still, still)
        r = subprocess.run(["bash", "-c", f'. "{HELPER}"; release_run_marker "{NAME}"'],
                           capture_output=True, text=True, env=env(tmp))
        still = marker(tmp).read_text() if marker(tmp).exists() else ""
        check("a process that did not write the marker cannot remove it", f"pid={d1.pid}" in still, still)
        os.kill(d1.pid, signal.SIGTERM)
        wait_for(lambda: not marker(tmp).exists())

        print("\nMALFORMED")
        (tmp / "running").mkdir(exist_ok=True)
        marker(tmp).write_text("garbage\n")
        rc, err = ask(tmp)
        check("an unreadable marker is an error, status 2", rc == 2, f"status {rc}")
        check("and the error names the file", f"{NAME}.marker" in err, repr(err))


def wiring() -> None:
    print("\nNO_MTIME / WIRED")
    helper = HELPER.read_text() if HELPER.exists() else ""
    code = "\n".join(l for l in helper.splitlines() if not l.lstrip().startswith("#"))
    # The detector is tested before it is trusted. Its first version matched the
    # word `stat` inside `ps -o stat=`, which reads process state, not a file.
    mtime = re.compile(r"(?<![\w=-])stat\s|\s-nt\s|\s-ot\s|-mmin|-newer|date\s+-r")
    for bad in ("stat -f %m file", "[ a -nt b ]", "[ a -ot b ]", "find . -newer x", "find . -mmin -5", "date -r f"):
        check(f"the mtime detector catches `{bad}`", mtime.search(bad) is not None)
    check("the mtime detector ignores `ps -o stat=`", mtime.search('ps -o stat= -p "$1"') is None)
    check("the helper never reads file mtime",
          bool(code) and not mtime.search(code),
          "found an mtime read, or there is no helper to inspect")
    check("the helper reads start time in UTC", "TZ=UTC ps" in code)

    grade = (REPO / "scripts" / "grade_loop.sh").read_text()
    gcode = "\n".join(l for l in grade.splitlines() if not l.lstrip().startswith("#"))
    fr = re.search(r"fetcher_running\(\)\s*\{(.*?)\n\}", gcode, re.S)
    body = fr.group(1) if fr else ""
    check("grade_loop sources the helper", ". scripts/run_marker.sh" in gcode)
    check("fetcher_running asks the markers", "run_marker_alive" in body, body)
    check("fetcher_running no longer parses process text",
          "ps -A" not in body and "pgrep" not in body and "awk" not in body, body)
    check("grade_loop stops loudly on a malformed marker",
          re.search(r"-eq 2\b[\s\S]{0,300}exit 1", gcode) is not None,
          "status 2 from the markers is not acted on")

    for loop in ("fetch_loop.sh", "happyscribe_loop.sh"):
        src = (REPO / "scripts" / loop).read_text()
        lcode = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        guard, claim = lcode.find("require_daemon_clone ||"), lcode.find("claim_run_marker")
        check(f"{loop} claims a marker named after itself",
              'claim_run_marker "$(basename "$0")" || exit 1' in lcode)
        check(f"{loop} claims after the daemon guard", 0 <= guard < claim, f"guard={guard} claim={claim}")

    gi = (REPO / "data" / ".gitignore").read_text() if (REPO / "data" / ".gitignore").exists() else ""
    check("data/.gitignore ignores the markers", "logs/running/" in gi)


def finish() -> int:
    for p in STARTED:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
