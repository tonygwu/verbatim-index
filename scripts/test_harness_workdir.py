"""Every harness call function must create the workdir it is handed.

The three call functions share one contract: the caller names a jail, the
callee runs there. `call_fable` and `call_gemini` honoured it by creating the
directory; `call_astra` did not, and passed a possibly-missing path straight to
`subprocess.run(cwd=...)`.

That was invisible for the whole corpus because Astra always EXTRACTED and
Gemini or Fable verified, so Astra was never handed the per-batch subdirectory
that `extract_predictions.verify_one` creates only the parent of. The first run
where measured quota routed Fable to extraction pushed Astra into verification
and lost 7 of 9 transcripts to `[Errno 2] No such file or directory: .../b0`.

The test does not call any model. It asserts the directory exists at the moment
the harness would launch, by intercepting the launch.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import grade  # noqa: E402

CHECKS = 0
FAILED: list[str] = []


def check(label: str, got, want) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILED.append(f"{label}\n     got:  {got!r}\n     want: {want!r}")


class Launched(Exception):
    """Raised by the stub to stop before any real process starts."""

    def __init__(self, cwd):
        self.cwd = cwd


def run_with_stub(fn, *a, **kw):
    """Call `fn`, intercepting subprocess.run, and report the cwd it asked for."""
    real = subprocess.run

    def stub(cmd, **kwargs):
        raise Launched(kwargs.get("cwd"))

    subprocess.run = stub
    try:
        fn(*a, **kw)
    except Launched as exc:
        return exc.cwd
    except Exception as exc:  # noqa: BLE001
        return f"unexpected:{type(exc).__name__}:{exc}"
    finally:
        subprocess.run = real
    return None


# --- astra: the regression -------------------------------------------------

with tempfile.TemporaryDirectory() as td:
    # A path whose PARENT exists and which does not: exactly verify_one's b0.
    jail = Path(td) / "job__verify__run" / "b0"
    jail.parent.mkdir(parents=True)
    check("astra jail does not exist before the call", jail.exists(), False)
    cwd = run_with_stub(grade.call_astra, "prompt", 60, jail)
    check("astra launches in the jail it was given", str(cwd), str(jail))
    check("astra CREATED the jail before launching", jail.is_dir(), True)

with tempfile.TemporaryDirectory() as td:
    # Several levels missing at once.
    jail = Path(td) / "a" / "b" / "c"
    run_with_stub(grade.call_astra, "prompt", 60, jail)
    check("astra creates missing parents too", jail.is_dir(), True)

with tempfile.TemporaryDirectory() as td:
    # An existing jail must not be disturbed.
    jail = Path(td) / "exists"
    jail.mkdir()
    (jail / "keep.txt").write_text("keep")
    run_with_stub(grade.call_astra, "prompt", 60, jail)
    check("astra leaves an existing jail alone", (jail / "keep.txt").read_text(), "keep")

with tempfile.TemporaryDirectory() as td:
    # A string, not a Path: verify_one passes Path, grade.py callers vary.
    jail = str(Path(td) / "as-a-string")
    run_with_stub(grade.call_astra, "prompt", 60, jail)
    check("astra accepts a str workdir", Path(jail).is_dir(), True)

# --- fable and gemini already honoured the contract; pin it ----------------

with tempfile.TemporaryDirectory() as td:
    jail = Path(td) / "fable" / "b0"
    cwd = run_with_stub(grade.call_fable, "prompt", None, 60, workdir=str(jail))
    check("fable creates its jail", jail.is_dir(), True)
    check("fable launches in its jail", str(cwd), str(jail))

print(f"test_harness_workdir: {CHECKS} checks, {len(FAILED)} failed")
for f in FAILED:
    print("  FAIL " + f)
sys.exit(1 if FAILED else 0)
