#!/usr/bin/env python3
"""run_tests.sh keeps every test's output and prints a failing test's tail (VI-29).

On 2026-10-18 a full run printed `FAILED scripts/test_pundits_contract.py` and nothing else; the
test then passed seven times alone, and nothing of the failing check survived. The runner now
writes each test's stdout and stderr to <GATE_DIR>/<utc>-<pid>/<test>.log and prints the last lines
of a failing test under its FAILED line; nothing prunes the run folders. Named tests
may be passed as arguments, which is how this test exercises it without running the whole suite
inside itself; the no-argument path is exercised in a throwaway git repository.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
RUNNER = ROOT / "scripts" / "run_tests.sh"
GUARD = "RUN_TESTS_SH_UNDER_TEST"

# Recursion guard. This test calls the runner with named tests. A runner that ignores its
# arguments runs the whole glob instead, which includes this file, which calls the runner
# again, without end: that happened on 2026-10-18 against the pre-VI-29 runner (four nested
# runs in ten minutes, killed by hand). The runner passes the environment through, so a
# nested copy of this file sees the mark and stops at once.
if os.environ.get(GUARD):
    sys.exit(f"{Path(__file__).name}: started under the runner it tests, so the runner ignored "
             "its arguments and ran the whole glob; refusing to recurse")


def run(tests: list[Path], gate_dir: Path | None, cwd: Path = ROOT) -> subprocess.CompletedProcess:
    env = {**os.environ, GUARD: "1"}
    env.pop("GATE_DIR", None)
    if gate_dir is not None:
        env["GATE_DIR"] = str(gate_dir)
    return subprocess.run(["bash", str(RUNNER), *map(str, tests)], cwd=cwd, env=env, text=True,
                          capture_output=True, check=False)


def failed_lines(stdout: str) -> list[str]:
    return re.findall(r"^FAILED .*$", stdout, re.M)


class RunTestsSh(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vi29-"))  # outside the repo: a killed run leaves no untracked file
        self.gate = Path(tempfile.mkdtemp(prefix="vi29-gate-"))
        self.good = self.tmp / "test_good.py"
        self.good.write_text("print('good ran')\n")
        self.bad = self.tmp / "test_bad.py"
        self.bad.write_text("import sys\nfor i in range(30): print(f'line {i}')\n"
                            "print('AssertionError: the needle', file=sys.stderr)\nsys.exit(1)\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.gate, ignore_errors=True)

    def only_run(self) -> Path:
        runs = list(self.gate.iterdir())
        self.assertEqual(len(runs), 1, runs)
        self.assertRegex(runs[0].name, r"^\d{8}T\d{6}Z-\d+$")
        return runs[0]

    def test_a_failing_test_prints_its_tail_and_keeps_its_log(self):
        r = run([self.good, self.bad], self.gate)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(failed_lines(r.stdout), [f"FAILED {self.bad}"])
        self.assertIn("AssertionError: the needle", r.stdout, "the failing test's last lines are printed")
        self.assertIn("line 29", r.stdout)
        self.assertNotIn("line 5\n", r.stdout, "only the tail is printed, not the whole log")
        self.assertIn("ran: 2\n", r.stdout)
        self.assertTrue(r.stdout.rstrip().endswith("failed: 1"), r.stdout)
        run_dir = self.only_run()
        logs = {p.name: p.read_text() for p in run_dir.iterdir()}
        self.assertEqual(set(logs), {"test_good.py.log", "test_bad.py.log"})
        self.assertIn("good ran", logs["test_good.py.log"])
        self.assertIn("line 0\n", logs["test_bad.py.log"], "the whole output is kept, not only the tail")
        self.assertTrue(logs["test_bad.py.log"].endswith("line 29\nAssertionError: the needle\n"),
                        "unbuffered: the log holds stdout and stderr in the order they were written")
        self.assertIn(f"logs: {self.gate}/{run_dir.name}\n", r.stdout)

    def test_a_log_with_no_final_newline_does_not_join_the_next_failed_line(self):
        cut = self.tmp / "test_cut.py"
        cut.write_text("import sys\nsys.stdout.write('killed mid-line')\nsys.exit(1)\n")
        r = run([cut, self.bad], self.gate)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(failed_lines(r.stdout), [f"FAILED {cut}", f"FAILED {self.bad}"],
                         "every FAILED line starts its own line, whatever the log ends with")
        self.assertIn("    killed mid-line\n", r.stdout)

    def test_a_test_named_twice_keeps_both_logs(self):
        r = run([self.bad, self.bad], self.gate)
        self.assertEqual(len(failed_lines(r.stdout)), 2)
        names = sorted(p.name for p in self.only_run().iterdir())
        self.assertEqual(names, ["test_bad.py.2.log", "test_bad.py.log"])

    def test_all_green_prints_failed_zero_and_exits_zero(self):
        r = run([self.good], self.gate)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(failed_lines(r.stdout), [])
        self.assertTrue(r.stdout.rstrip().endswith("failed: 0"), r.stdout)

    def test_named_tests_skip_the_node_test(self):
        run([self.good], self.gate)
        self.assertEqual([p.name for p in self.only_run().iterdir()], ["test_good.py.log"])

    def test_run_folders_are_never_pruned(self):
        """A prune was reviewed and dropped: it deleted every subfolder of GATE_DIR, links' targets too."""
        for _ in range(3):
            run([self.good], self.gate)
        other = self.gate / "not-a-run"
        other.mkdir()
        run([self.good], self.gate)
        runs = sorted(p.name for p in self.gate.iterdir())
        self.assertEqual(len(runs), 5, runs)
        self.assertIn("not-a-run", runs)
        self.assertNotRegex(RUNNER.read_text(), r"\brm\b", "the runner deletes nothing")

    def test_no_arguments_runs_the_glob_and_the_node_test(self):
        """The production gate: every scripts/test_*.py plus node scripts/test_site_tooltip.js.

        Run in a throwaway git repository, so the glob finds two fake tests and never this file.
        """
        repo = self.tmp / "repo"
        (repo / "scripts").mkdir(parents=True)
        (repo / ".venv" / "bin").mkdir(parents=True)
        os.symlink(sys.executable, repo / ".venv" / "bin" / "python")
        subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q"], cwd=repo, check=True)
        (repo / "scripts" / "test_a.py").write_text("print('a ran')\n")
        (repo / "scripts" / "test_b.py").write_text("import sys; print('b broke'); sys.exit(1)\n")
        (repo / "scripts" / "test_site_tooltip.js").write_text("console.log('js ran'); process.exit(0);\n")
        r = run([], None, cwd=repo)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        # Spelled in parts: test_script_references.py reads a literal scripts/<name> as a reference.
        self.assertEqual(failed_lines(r.stdout), [f"FAILED {Path('scripts') / 'test_b.py'}"])
        self.assertIn("    b broke\n", r.stdout)
        self.assertIn("ran: 3\n", r.stdout)
        gate = repo / ".gate"
        runs = list(gate.iterdir())
        self.assertEqual(len(runs), 1, runs)
        logs = {p.name: p.read_text() for p in runs[0].iterdir()}
        self.assertEqual(set(logs), {"test_a.py.log", "test_b.py.log", "test_site_tooltip.js.log"})
        self.assertEqual(logs["test_site_tooltip.js.log"], "js ran\n")
        self.assertIn(f"logs: .gate/{runs[0].name}\n", r.stdout)

    def test_gate_folder_is_git_ignored(self):
        r = subprocess.run(["git", "check-ignore", "-q", ".gate/x/y.log"], cwd=ROOT, check=False)
        self.assertEqual(r.returncode, 0, ".gate/ must be ignored so a run never dirties the tree")

    def test_header_names_the_knobs(self):
        text = RUNNER.read_text()
        for needle in ("VI-29", ".gate/<utc>-<pid>/", "GATE_DIR", "git-ignored", "stderr", "Nothing prunes"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main(verbosity=1)
