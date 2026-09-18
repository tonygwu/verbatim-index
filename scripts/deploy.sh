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
# The SAME exclusions aggregate.load_grades applies, or the two counts disagree
# and this check refuses for ever. _raw holds judge transcripts and _obsolete
# holds grades moved aside by `grade.py --force`; neither is a score. deploy.sh
# was the only one of the three out of step: aggregate.py has skipped _obsolete
# since contract v2 arrived, and deploy_pundits.sh skips it too. Latent rather
# than live today, because _obsolete is written only under contract v2 and
# leaders is v1, so nothing under data/grades has ever landed there. It would
# have bitten the day leaders moved to v2, and --refresh could not have fixed it:
# re-aggregating still excludes the file that deploy was counting.
SKIP = {"_raw", "_obsolete"}
on_disk = sum(1 for p in (data / "grades").rglob("*.json")
              if not SKIP & set(p.parts))
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

# THE PUBLICATION FLOOR. A board that collapsed must not publish over the board
# that did not. Membership made that reachable: "leader" typed for "leaders"
# across membership.json is valid JSON naming no unknown slug, and every grade
# would land off-board, render zero leaders and publish, because the block above
# prints the count and applies no floor.
#
# The floor is the PREVIOUS PUBLISHED COUNT, in site/published.json beside the
# page. It is not in the data repository, because deploy.sh stays read-only on
# data. scripts/publication_floor.py carries the reasoning and the one threshold.
LEADERS_PUBLISHED="$($PY - "$PRODUCTION_DATA" <<'EOF'
import json, pathlib, sys
r = json.loads((pathlib.Path(sys.argv[1]) / "results.json").read_text())
print(sum(1 for l in r["leaders"] if l["status"] == "scored"))
EOF
)"
# Runs on --dry-run too: a dry run is where an operator finds out.
$PY scripts/publication_floor.py check --site-dir site --count "$LEADERS_PUBLISHED"

if [ "$DRY" -eq 1 ]; then
  echo "--dry-run: rendered site/index.html, published nothing"
  exit 0
fi
npx wrangler deploy
# AFTER the publish, never before: recording a baseline for a publication that
# failed would raise the floor to a board that never went live.
$PY scripts/publication_floor.py record --site-dir site --count "$LEADERS_PUBLISHED" \
    --results "${PRODUCTION_DATA}/results.json" --data-revision "${DATA_REVISION}"
