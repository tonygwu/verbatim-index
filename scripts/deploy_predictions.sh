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

# The Score column is data-driven and OPTIONAL. Without a scores file the page
# renders the column empty and says why, which is the honest default. With one,
# that file must live under the SAME production checkout as everything else being
# published: a scores.json from an experiment run would put an unreviewed number
# on the live site through a path that bypasses every other production guard.
SCORES_ARG=()
SCORES="${PRODUCTION_DATA}/predictions/scores.json"
if [ -f "$SCORES" ]; then
  SCORES_REAL="$(cd "$(dirname "$SCORES")" && pwd -P)/$(basename "$SCORES")"
  case "$SCORES_REAL" in
    "${PRODUCTION_DATA}"/*) SCORES_ARG=(--scores "$SCORES_REAL") ;;
    *) echo "refusing to publish scores from outside the production checkout: $SCORES_REAL" >&2; exit 1 ;;
  esac
  echo "scores: publishing ${SCORES_REAL}"
else
  echo "scores: none at ${SCORES}; the Score column will render empty"
fi

$PY scripts/build_predictions_site.py --index "${PRODUCTION_DATA}/predictions/index.json" --predictions "${PRODUCTION_DATA}/predictions" \
    --roster "${PRODUCTION_DATA}/roster/final.json" --out site-predictions/index.html \
    ${SCORES_ARG[@]+"${SCORES_ARG[@]}"}   # empty-array-safe: bash 3.2 calls a bare "${a[@]}" unbound under set -u

# What is about to ship, and whether the index is behind the files on disk.
$PY - "$PRODUCTION_DATA" <<'EOF'
import hashlib, json, pathlib, sys
sys.path.insert(0, "scripts")
from data_clone_workflow import prediction_inputs_sha256
data = pathlib.Path(sys.argv[1])
idx = json.load((data / "predictions/index.json").open())
c = idx["corpus"]
print(f"about to publish {len(idx['leaders'])} people, {c['accepted']} accepted predictions from "
      f"{c['transcripts_with_accepted']} transcripts, index generated {idx['generated_at_utc']}, "
      f"runs {len(idx['run_ids_seen'])}")
files = [p for p in (data / "predictions").glob("*/*.jsonl") if not p.parent.name.startswith("_")]
lines = sum(1 for p in files for _ in open(p))
digest = prediction_inputs_sha256(data / "predictions")
roster_digest = hashlib.sha256((data / "roster/final.json").read_bytes()).hexdigest()
if any(k not in idx for k in ("files_read", "records_read", "inputs_sha256")):
    print("index.json predates inputs_sha256; staleness cannot be checked")
    raise SystemExit("REFUSING: refresh the production index before publication")
elif "roster_sha256" not in idx:
    # THE ROSTER IS AN INPUT inputs_sha256 cannot see. aggregate_predictions.py
    # unions roster slugs with every slug that has records, so the roster can
    # change while every record stays byte-identical and all three counts match.
    print("index.json predates roster_sha256, so a roster change since it was "
          "built cannot be detected")
    raise SystemExit("REFUSING: re-run aggregate_predictions.py from repo-0")
elif idx["roster_sha256"] != roster_digest:
    print(f"STALE: the roster changed since the index was built "
          f"(index {idx['roster_sha256'][:12]}, disk {roster_digest[:12]}). The "
          f"index unions roster slugs, so it lists the wrong people even though "
          f"every record is unchanged; re-run aggregate_predictions.py from repo-0")
    raise SystemExit("REFUSING: stale production index")
elif (idx["files_read"], idx["records_read"]) != (len(files), lines):
    print(f"STALE: index read {idx['files_read']} files / {idx['records_read']} records, disk has {len(files)} / {lines}; "
          f"re-run aggregate_predictions.py from repo-0 before deploying")
    raise SystemExit("REFUSING: stale production index")
elif idx["inputs_sha256"] != digest:
    # Verification and market consensus rewrite records in place, so counts can
    # match while the index describes an older corpus.
    print(f"STALE: counts match ({len(files)} files, {lines} records) but record contents changed since the index "
          f"was built (index {idx['inputs_sha256'][:12]}, disk {digest[:12]}); re-run aggregate_predictions.py from repo-0")
    raise SystemExit("REFUSING: stale production index")
else:
    print(f"current: index matches disk ({len(files)} files, {lines} records, inputs sha256 {digest[:12]})")
EOF

check_publication_unchanged

if [ "$DRY" -eq 1 ]; then
  echo "--dry-run: rendered site-predictions/index.html, published nothing"
  exit 0
fi
npx wrangler deploy -c wrangler.predictions.toml
