#!/usr/bin/env bash
# Render Verbatim Pundits from the explicitly named pundits production checkout,
# then publish it to verbatim-pundits.tonygwu.com. See docs/DATA-CLONE-WORKFLOW.md
# and docs/PUNDITS-PLAN.md (P4, P11). --dry-run renders but does not publish;
# --refresh first re-aggregates the production results and requires the owner.
#
#   bash scripts/deploy_pundits.sh --production-data data-pundits \
#       --data-revision "$(git -C data-pundits rev-parse HEAD)" --dry-run
#
# Publication is P11 and needs the operator's explicit approval.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
# Every guard below resolves by study: the production source must be the
# checkout registered under verbatim.pundits.productionData, carry a .study
# naming pundits, and have the verbatim-pundits-data origin.
export STUDY=pundits
. scripts/study_env.sh
. scripts/deploy_source.sh
PUBLICATION_SITE=pundits

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

# The same invocation grade_loop.sh uses for this study.
$PY scripts/build_site.py --results "${PRODUCTION_DATA}/results.json" --audit "${PRODUCTION_DATA}/results_audit.json" \
    --roster "${PRODUCTION_DATA}/roster/final.json" --calibration "${PRODUCTION_DATA}/logs/calibration.json" \
    --sources "${PRODUCTION_DATA}/sources/discovered.json" --out "${SITE_DIR}/index.html"

$PY - "$PRODUCTION_DATA" <<'EOF'
import json, pathlib, sys
data = pathlib.Path(sys.argv[1])
r = json.loads((data / "results.json").read_text())
people = sorted([p for p in r["leaders"] if p.get("status") == "scored"],
                key=lambda p: -(p.get("blinded") or {}).get("overall", 0))
print(f"about to publish {len(people)} people, {r['diagnostics'].get('grades_used')} grades used")
for i, p in enumerate(people[:3], 1):
    print(f"  {i}. {p['name']} {(p.get('blinded') or {}).get('overall')} on {p.get('n_transcripts')} transcripts")

# Staleness, stated on every deploy. Only grade files count: _raw holds judge
# text, _obsolete holds grades moved aside by grade.py --force, and _provenance
# holds run records. aggregate.py counts none of them, so neither does this.
skip = {"_raw", "_obsolete", "_provenance"}
on_disk = sum(1 for p in (data / "grades").rglob("*.json") if not skip & set(p.parts))
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
  echo "--dry-run: rendered ${SITE_DIR}/index.html, published nothing"
  exit 0
fi
npx wrangler deploy -c wrangler.pundits.toml
