#!/usr/bin/env bash
# Render the leaderboard from the shared data and publish it. Runnable from any
# clone, because data/ is one checkout that every clone points at.
#
# The render is not optional. site/index.html is a per-clone build artifact, so
# a clone that has never rendered holds nothing and one that rendered yesterday
# holds yesterday's ranking. Rendering here means the published page always
# matches data/results.json as it stands at the moment you deploy.
#
#   bash scripts/deploy.sh            # render, then publish
#   bash scripts/deploy.sh --dry-run  # render and report, publish nothing
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

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
EOF

if [ "$DRY" -eq 1 ]; then
  echo "--dry-run: rendered site/index.html, published nothing"
  exit 0
fi
npx wrangler deploy
