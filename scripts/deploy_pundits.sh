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
#
# Provenance (2026-10-12): the page and site-pundits/revision.json name the data
# revision. Before publishing, the live revision.json must be an ancestor of
# ours, so an older render never replaces a newer page; the first deploy after
# this check existed passes --first-revision-deploy once, because the live page
# had no revision.json. After publishing, the live revision is read back and
# must equal ours. LIVE_CONFIRM_ATTEMPTS and LIVE_CONFIRM_WAIT are test seams.
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

# The page's date is the data revision's commit time, in UTC, never a clock.
DATA_DATE="$($PY -c 'import datetime, sys; print(datetime.datetime.fromtimestamp(int(sys.argv[1]), datetime.timezone.utc).date())' \
  "$(git -C "$PRODUCTION_DATA" show -s --format=%ct "$DATA_REVISION")")" || { echo "REFUSING: cannot read the data revision's date" >&2; exit 1; }

# Owner mode renders the daemon's uncommitted output, so the stamp says when the
# published inputs differ from the commit it names.
DATA_UNCOMMITTED="$($PY scripts/data_clone_workflow.py publication-dirty --production-data "$PRODUCTION_DATA" \
  --site pundits)" || { echo "REFUSING: cannot tell whether the published inputs are committed" >&2; exit 1; }
UNCOMMITTED=()
[ "$DATA_UNCOMMITTED" = "yes" ] && UNCOMMITTED=(--data-uncommitted)

# The same invocation grade_loop.sh uses for this study, plus the provenance stamp.
$PY scripts/build_site.py --results "${PRODUCTION_DATA}/results.json" --audit "${PRODUCTION_DATA}/results_audit.json" \
    --roster "${PRODUCTION_DATA}/roster/final.json" --calibration "${PRODUCTION_DATA}/logs/calibration.json" \
    --sources "${PRODUCTION_DATA}/sources/discovered.json" --out "${SITE_DIR}/index.html" \
    --data-revision "$DATA_REVISION" --data-date "$DATA_DATE" --transcripts-meta "${PRODUCTION_DATA}/transcripts_open" \
    ${UNCOMMITTED[@]+"${UNCOMMITTED[@]}"}

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

# The page's own provenance, served no-store so the next deploy can refuse to
# replace a newer page with an older one. Owner mode renders the daemon's
# uncommitted output, so the content fingerprint is recorded beside the commit.
PUBLIC_HEAD="$(git rev-parse --verify -q HEAD || true)"
[ -n "$PUBLIC_HEAD" ] || echo "public revision: this public tree has no commit; revision.json records null"
$PY - "${SITE_DIR}" "$DATA_REVISION" "$DATA_DATE" "$PUBLICATION_BEFORE" "$PUBLIC_HEAD" "$DATA_UNCOMMITTED" <<'EOF'
import json, pathlib, sys
site, data_revision, data_date, content, public, uncommitted = sys.argv[1:7]
if uncommitted not in ("yes", "no"):
    raise SystemExit(f"REFUSING: publication-dirty said {uncommitted!r}")
out = pathlib.Path(site)
(out / "revision.json").write_text(json.dumps(
    {"data_revision": data_revision, "data_date": data_date, "content_sha256": content,
     "data_uncommitted": uncommitted == "yes", "public_revision": public or None},
    indent=1, sort_keys=True) + "\n")
(out / "_headers").write_text(
    "# Written by scripts/deploy_pundits.sh. Cloudflare reads this file and does not serve it.\n"
    "/revision.json\n  Cache-Control: no-store\n")
EOF
FIRST=()
[ "$FIRST_REVISION" -eq 1 ] && FIRST=(--first-revision-deploy)
# At the same data revision the live page's public code must be an ancestor of ours.
[ -n "$PUBLIC_HEAD" ] && FIRST+=(--public-revision "$PUBLIC_HEAD")
$PY scripts/data_clone_workflow.py live-revision --site pundits --production-data "$PRODUCTION_DATA" \
    --data-revision "$DATA_REVISION" ${FIRST[@]+"${FIRST[@]}"}
echo "the live page is not newer than data revision ${DATA_REVISION:0:12}"

if [ "$DRY" -eq 1 ]; then
  echo "--dry-run: rendered ${SITE_DIR}/index.html, published nothing"
  exit 0
fi
npx wrangler deploy -c wrangler.pundits.toml
# P11 verification: the live revision.json must equal the one this deploy wrote,
# whole, and the live page must carry this data revision. An earlier page at the
# same data revision differs in content_sha256; a grade_loop.sh render that
# replaced site-pundits/index.html before the upload carries no revision stamp.
$PY scripts/data_clone_workflow.py live-revision --site pundits --confirm --production-data "$PRODUCTION_DATA" \
    --data-revision "$DATA_REVISION" --expect "${SITE_DIR}/revision.json" --page \
    --attempts "${LIVE_CONFIRM_ATTEMPTS:-12}" --wait-seconds "${LIVE_CONFIRM_WAIT:-10}"
