#!/usr/bin/env bash
# Render the leaderboard from the shared data and publish it. Runnable from any
# clone, because data/ is one checkout that every clone points at.
#
# The render is not optional. site/index.html is a per-clone build artifact, so
# a clone that has never rendered holds nothing and one that rendered yesterday
# holds yesterday's ranking. Rendering here means the published page always
# matches data/results.json as it stands at the moment you deploy.
#
# Rendering matches the page to data/results.json. It does NOT match
# results.json to the grades: only aggregate.py does that, and it is the
# grading loop that normally runs it. So a deploy between loop cycles
# republishes the last cycle's numbers. On 2026-09-07 that shipped a board
# where Jeff Bezos read 5 transcripts and 8 of his had scored, twice, because
# the deploy looked like it had worked both times. --refresh closes that, and
# the staleness line below makes the gap visible when you do not pass it.
#
#   bash scripts/deploy.sh            # render, then publish
#   bash scripts/deploy.sh --refresh  # re-aggregate first, then render and publish
#   bash scripts/deploy.sh --dry-run  # render and report, publish nothing
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
DRY=0
REFRESH=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --refresh) REFRESH=1 ;;
    *) echo "unknown argument: $arg" >&2
       echo "usage: deploy.sh [--refresh] [--dry-run]" >&2; exit 2 ;;
  esac
done

# --refresh WRITES data/results.json, and every clone shares one data checkout,
# so it carries the same precondition the daemons do. A plain deploy stays
# read-only on data/ and runnable from any clone.
if [ "$REFRESH" -eq 1 ]; then
  . scripts/daemon_guard.sh
  require_daemon_clone || exit 1
  echo "--refresh: re-aggregating data/results.json from data/grades"
  # grade_loop.sh's own invocation, so this produces the file the loop would.
  $PY scripts/aggregate.py --grades data/grades --roster data/roster/final.json \
      --transcripts data/transcripts_blind --out data/results.json > /dev/null
fi

[ -f data/results.json ] || { echo "no data/results.json; nothing to publish" >&2; exit 1; }

# The same invocation grade_loop.sh uses. Kept identical on purpose: a deploy
# that renders with different arguments publishes a different page from the one
# the loop renders, which is the failure this script exists to prevent.
$PY scripts/build_site.py --results data/results.json --audit data/results_audit.json \
    --roster data/roster/final.json --calibration data/logs/calibration.json \
    --sources data/sources/discovered.json --out site/index.html

$PY - <<'EOF'
import json, pathlib
r = json.loads(pathlib.Path("data/results.json").read_text())
led = sorted([l for l in r["leaders"] if l["status"] == "scored"],
             key=lambda l: -l["blinded"]["overall"])
print(f"about to publish {len(led)} leaders, {r['diagnostics']['grades_used']} grades used")
for i, l in enumerate(led[:3], 1):
    print(f"  {i}. {l['name']} {l['blinded']['overall']} on {l['n_transcripts']} transcripts")

# Staleness, stated rather than left to be inferred. grades_loaded is every
# grade file aggregate.py read, so comparing it to what is on disk now says
# exactly how far behind results.json is. Silence here is the failure mode
# --refresh exists to prevent, so this prints on every deploy.
on_disk = sum(1 for p in pathlib.Path("data/grades").rglob("*.json")
              if "_raw" not in p.parts)
# grade_files_read is the count BEFORE any filter, which is the only figure
# comparable to a count of files. grades_loaded is post-filter and would report
# a permanent false staleness equal to the rows the subject-share cutoff drops.
read_n = r["diagnostics"].get("grade_files_read")
if read_n is None:
    print("  results.json predates grade_files_read; staleness cannot be checked")
elif on_disk > read_n:
    print(f"  STALE: results.json was built from {read_n} grade files, {on_disk} are "
          f"on disk now ({on_disk - read_n} newer). Re-run with --refresh to include them.")
else:
    print(f"  current: results.json covers all {on_disk} grade files on disk")
EOF

if [ "$DRY" -eq 1 ]; then
  echo "--dry-run: rendered site/index.html, published nothing"
  exit 0
fi
npx wrangler deploy
