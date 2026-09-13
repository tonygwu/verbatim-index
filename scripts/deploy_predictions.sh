#!/usr/bin/env bash
# Render from the explicitly named production checkout, then publish.
# See docs/DATA-CLONE-WORKFLOW.md. --dry-run renders but does not publish;
# --refresh first regenerates the production index and requires its owner.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
. scripts/deploy_source.sh
PUBLICATION_SITE=predictions

if [ "$REFRESH" -eq 1 ]; then
  # shellcheck source=scripts/daemon_guard.sh
  . scripts/daemon_guard.sh
  require_daemon_clone || exit 1
  $PY scripts/aggregate_predictions.py --predictions "${PRODUCTION_DATA}/predictions" --roster "${PRODUCTION_DATA}/roster/final.json" \
      --transcripts "${PRODUCTION_DATA}/transcripts_open" --out "${PRODUCTION_DATA}/predictions/index.json"
fi

PUBLICATION_BEFORE="$(publication_fingerprint)"

[ -f "${PRODUCTION_DATA}/predictions/index.json" ] || { echo "no ${PRODUCTION_DATA}/predictions/index.json; run aggregate_predictions.py first (from repo-0, or --refresh there)" >&2; exit 1; }

$PY scripts/build_predictions_site.py --index "${PRODUCTION_DATA}/predictions/index.json" --predictions "${PRODUCTION_DATA}/predictions" \
    --roster "${PRODUCTION_DATA}/roster/final.json" --out site-predictions/index.html

# What is about to ship, and whether the index is behind the files on disk.
$PY - "$PRODUCTION_DATA" <<'EOF'
import json, pathlib, sys
data = pathlib.Path(sys.argv[1])
idx = json.load((data / "predictions/index.json").open())
c = idx["corpus"]
print(f"about to publish {len(idx['leaders'])} people, {c['accepted']} accepted predictions from "
      f"{c['transcripts_with_accepted']} transcripts, index generated {idx['generated_at_utc']}, "
      f"runs {len(idx['run_ids_seen'])}")
files = [p for p in (data / "predictions").glob("*/*.jsonl") if not p.parent.name.startswith("_")]
lines = sum(1 for p in files for _ in open(p))
if "files_read" not in idx or "records_read" not in idx:
    print("index.json predates records_read; staleness cannot be checked")
    raise SystemExit("REFUSING: refresh the production index before publication")
elif (idx["files_read"], idx["records_read"]) != (len(files), lines):
    print(f"STALE: index read {idx['files_read']} files / {idx['records_read']} records, disk has {len(files)} / {lines}; "
          f"re-run aggregate_predictions.py from repo-0 before deploying")
    raise SystemExit("REFUSING: stale production index")
else:
    print(f"current: index matches disk ({len(files)} files, {lines} records)")
EOF

check_publication_unchanged

if [ "$DRY" -eq 1 ]; then
  echo "--dry-run: rendered site-predictions/index.html, published nothing"
  exit 0
fi
npx wrangler deploy -c wrangler.predictions.toml
