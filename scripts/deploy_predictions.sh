#!/usr/bin/env bash
# Render the predictions page from data/predictions and deploy it to
# verbatim-predictions.tonygwu.com. Runnable from ANY clone: a plain deploy
# reads data/ and writes only site-predictions/index.html, which is a build
# artifact and gitignored.
#
#   bash scripts/deploy_predictions.sh            render, print what will ship, deploy
#   bash scripts/deploy_predictions.sh --dry-run  render and print, publish nothing
#   bash scripts/deploy_predictions.sh --refresh  re-aggregate data/predictions/index.json first
#
# --refresh writes under data/predictions, so it is guarded the same way the
# loops are: it runs only in the clone that data/.daemon-clone names. Everything
# else in this script is read-only on data/.
#
# The page is ALWAYS re-rendered before a deploy. deploy.sh documents why: a
# deploy that skips the render publishes whatever index.html happened to be
# on disk, which once meant a page hours older than the data beside it.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
DRY=0
REFRESH=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --refresh) REFRESH=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [ "$REFRESH" -eq 1 ]; then
  # shellcheck source=scripts/daemon_guard.sh
  . scripts/daemon_guard.sh
  require_daemon_clone || exit 1
  $PY scripts/aggregate_predictions.py --predictions data/predictions --roster data/roster/final.json \
      --transcripts data/transcripts_open --out data/predictions/index.json
fi

[ -f data/predictions/index.json ] || { echo "no data/predictions/index.json; run aggregate_predictions.py first (from repo-0, or --refresh there)" >&2; exit 1; }

$PY scripts/build_predictions_site.py --index data/predictions/index.json --predictions data/predictions \
    --roster data/roster/final.json --out site-predictions/index.html

# What is about to ship, and whether the index is behind the files on disk.
$PY - <<'EOF'
import json, glob
idx = json.load(open("data/predictions/index.json"))
c = idx["corpus"]
print(f"about to publish {len(idx['leaders'])} people, {c['accepted']} accepted predictions from "
      f"{c['transcripts_with_accepted']} transcripts, index generated {idx['generated_at_utc']}, "
      f"runs {len(idx['run_ids_seen'])}")
files = [p for p in glob.glob("data/predictions/*/*.jsonl") if not p.split("/")[-2].startswith("_")]
lines = sum(1 for p in files for _ in open(p))
if "files_read" not in idx or "records_read" not in idx:
    print("index.json predates records_read; staleness cannot be checked")
elif (idx["files_read"], idx["records_read"]) != (len(files), lines):
    print(f"STALE: index read {idx['files_read']} files / {idx['records_read']} records, disk has {len(files)} / {lines}; "
          f"re-run aggregate_predictions.py from repo-0 before deploying")
else:
    print(f"current: index matches disk ({len(files)} files, {lines} records)")
EOF

if [ "$DRY" -eq 1 ]; then
  echo "--dry-run: rendered site-predictions/index.html, published nothing"
  exit 0
fi
npx wrangler deploy -c wrangler.predictions.toml
