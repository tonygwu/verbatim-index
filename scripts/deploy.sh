#!/usr/bin/env bash
# Render from the explicitly named production checkout, then publish.
# See docs/DATA-CLONE-WORKFLOW.md. --dry-run renders but does not publish;
# --refresh first regenerates the production index and requires its owner.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
. scripts/deploy_source.sh
PUBLICATION_SITE=leaderboard

if [ "$REFRESH" -eq 1 ]; then
  . scripts/daemon_guard.sh
  require_daemon_clone || exit 1
  echo "--refresh: re-aggregating ${PRODUCTION_DATA}/results.json from ${PRODUCTION_DATA}/grades"
  # grade_loop.sh's own invocation, so this produces the file the loop would.
  $PY scripts/aggregate.py --grades "${PRODUCTION_DATA}/grades" --roster "${PRODUCTION_DATA}/roster/final.json" \
      --transcripts "${PRODUCTION_DATA}/transcripts_blind" --out "${PRODUCTION_DATA}/results.json" > /dev/null
fi

PUBLICATION_BEFORE="$(publication_fingerprint)"

[ -f "${PRODUCTION_DATA}/results.json" ] || { echo "no ${PRODUCTION_DATA}/results.json; nothing to publish" >&2; exit 1; }

# The same invocation grade_loop.sh uses. Kept identical on purpose: a deploy
# that renders with different arguments publishes a different page from the one
# the loop renders, which is the failure this script exists to prevent.
$PY scripts/build_site.py --results "${PRODUCTION_DATA}/results.json" --audit "${PRODUCTION_DATA}/results_audit.json" \
    --roster "${PRODUCTION_DATA}/roster/final.json" --calibration "${PRODUCTION_DATA}/logs/calibration.json" \
    --sources "${PRODUCTION_DATA}/sources/discovered.json" --out site/index.html

$PY - "$PRODUCTION_DATA" <<'EOF'
import json, pathlib, sys
data = pathlib.Path(sys.argv[1])
r = json.loads((data / "results.json").read_text())
led = sorted([l for l in r["leaders"] if l["status"] == "scored"],
             key=lambda l: -l["blinded"]["overall"])
print(f"about to publish {len(led)} leaders, {r['diagnostics']['grades_used']} grades used")
for i, l in enumerate(led[:3], 1):
    print(f"  {i}. {l['name']} {l['blinded']['overall']} on {l['n_transcripts']} transcripts")

# Staleness, stated rather than left to be inferred. grades_loaded is every
# grade file aggregate.py read, so comparing it to what is on disk now says
# exactly how far behind results.json is. Silence here is the failure mode
# --refresh exists to prevent, so this prints on every deploy.
on_disk = sum(1 for p in (data / "grades").rglob("*.json")
              if "_raw" not in p.parts)
# grade_files_read is the count BEFORE any filter, which is the only figure
# comparable to a count of files. grades_loaded is post-filter and would report
# a permanent false staleness equal to the rows the subject-share cutoff drops.
read_n = r["diagnostics"].get("grade_files_read")
if read_n is None:
    print("  results.json predates grade_files_read; staleness cannot be checked")
    raise SystemExit("REFUSING: refresh the production aggregate before publication")
elif on_disk != read_n:
    print(f"  STALE: results.json was built from {read_n} grade files, {on_disk} are "
          f"on disk now ({on_disk - read_n} newer). Re-run with --refresh to include them.")
    raise SystemExit("REFUSING: stale production aggregate")
else:
    print(f"  current: results.json covers all {on_disk} grade files on disk")
EOF

check_publication_unchanged

if [ "$DRY" -eq 1 ]; then
  echo "--dry-run: rendered site/index.html, published nothing"
  exit 0
fi
npx wrangler deploy
