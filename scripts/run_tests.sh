#!/usr/bin/env bash
# Fail-loud suite runner (pundits plan, Verification). Globbed, never a typed list,
# so a new test file is run the day it is added. Exits nonzero if any test fails.
# No test spends judge quota.
#   bash scripts/run_tests.sh
cd "$(git rev-parse --show-toplevel)" || exit 2
fails=0
for t in scripts/test_*.py; do .venv/bin/python "$t" >/dev/null || { echo "FAILED $t"; fails=$((fails+1)); }; done
node scripts/test_site_tooltip.js >/dev/null || { echo "FAILED test_site_tooltip.js"; fails=$((fails+1)); }
echo "failed: $fails"; [ "$fails" -eq 0 ]
