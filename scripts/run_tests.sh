#!/usr/bin/env bash
# Fail-loud suite runner (pundits plan, Verification). Globbed, never a typed list,
# so a new test file is run the day it is added. Exits nonzero if any test fails.
# No test spends judge quota.
#   bash scripts/run_tests.sh              # every scripts/test_*.py plus the Node test
#   bash scripts/run_tests.sh <test>...    # only the named tests (no Node test)
# Each test's stdout AND stderr go to .gate/<utc>-<pid>/<test>.log (git-ignored);
# a test named twice gets <test>.2.log. The terminal gets only the FAILED lines,
# each followed by the last 20 lines of its log, then `ran: N`, `logs: <folder>`
# and `failed: N` (VI-29: a one-off failure left no text). So a warning a test
# used to print to the terminal is now in its log only. GATE_DIR moves the
# folder (a relative path is under the repo root). Nothing prunes the folder:
# a full run adds about 1 MB, and a prune that deleted old runs was reviewed
# and dropped (it would also delete whatever else lives under GATE_DIR), so
# delete the run folders yourself. The folder name is a UTC stamp of when the
# run started plus the pid, not a time read from any data.
# Python runs unbuffered: with stdout redirected to a file it is block-buffered,
# so a test's prints would land in the log AFTER the unittest report on stderr,
# and the tail would show the prints, not the report.
cd "$(git rev-parse --show-toplevel)" || exit 2
run="${GATE_DIR:-.gate}/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$run" || exit 2
fails=0
report() { # <label> <log>; awk, not sed: a log with no final newline must not join the next line
  echo "FAILED $1"; tail -n 20 "$2" | awk '{print "    " $0}'; fails=$((fails+1))
}
logfile() { # <test> -> a log path not yet used in this run
  local l="$run/$(basename "$1").log" n=1
  while [ -e "$l" ]; do n=$((n+1)); l="$run/$(basename "$1").$n.log"; done
  echo "$l"
}
if [ "$#" -gt 0 ]; then tests=("$@"); else tests=(scripts/test_*.py); fi
for t in "${tests[@]}"; do
  log="$(logfile "$t")"
  PYTHONUNBUFFERED=1 .venv/bin/python "$t" >"$log" 2>&1 || report "$t" "$log"
done
ran=${#tests[@]}
if [ "$#" -eq 0 ]; then
  log="$(logfile test_site_tooltip.js)"
  node scripts/test_site_tooltip.js >"$log" 2>&1 || report "test_site_tooltip.js" "$log"
  ran=$((ran+1))
fi
echo "ran: $ran"
echo "logs: $run"
echo "failed: $fails"; [ "$fails" -eq 0 ]
