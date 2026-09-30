#!/usr/bin/env bash
# Render the predictions site from a data checkout at exactly origin/main, then
# publish. ANY clone with a push role may run it (origin mode, plan phase P5 in
# docs/plans/shared-data-push-2026-09-27.md): the data and public checkouts must
# both be at their freshly fetched origin/main with published paths clean, and
# the live page must not be newer. --dry-run renders and checks, publishes
# nothing. --first-revision-deploy allows one deploy when the live page carries
# no revision.json yet. --refresh is gone: regenerate with data_sync.py push.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
PUBLICATION_SITE=predictions
PUBLICATION_MODE=origin
. scripts/deploy_source.sh

PUBLICATION_BEFORE="$(publication_fingerprint)"

[ -f "${PRODUCTION_DATA}/predictions/index.json" ] || { echo "no ${PRODUCTION_DATA}/predictions/index.json; regenerate it and push with scripts/data_sync.py push" >&2; exit 1; }

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

# The page's date is the data revision's commit time, in UTC, never a clock.
DATA_DATE="$($PY -c 'import datetime, sys; print(datetime.datetime.fromtimestamp(int(sys.argv[1]), datetime.timezone.utc).date())' \
  "$(git -C "$PRODUCTION_DATA" show -s --format=%ct "$DATA_REVISION")")" || { echo "REFUSING: cannot read the data revision's date" >&2; exit 1; }
$PY scripts/build_predictions_site.py --data-date "$DATA_DATE" --index "${PRODUCTION_DATA}/predictions/index.json" --predictions "${PRODUCTION_DATA}/predictions" \
    --roster "${PRODUCTION_DATA}/roster/final.json" --out site-predictions/index.html \
    ${SCORES_ARG[@]+"${SCORES_ARG[@]}"}   # empty-array-safe: bash 3.2 calls a bare "${a[@]}" unbound under set -u

# What is about to ship, and whether any derived file is behind its inputs. The
# checks live in data_clone_workflow (index_staleness, scores_staleness), which
# imports no model harness, so data_sync.py applies exactly the same ones.
$PY - "$PRODUCTION_DATA" "$DATA_REVISION" <<'EOF'
import json, pathlib, sys
sys.path.insert(0, "scripts")
import data_clone_workflow as D
data = pathlib.Path(sys.argv[1])
idx = json.load((data / "predictions/index.json").open())
c = idx["corpus"]
print(f"about to publish {len(idx['leaders'])} people, {c['accepted']} accepted predictions from "
      f"{c['transcripts_with_accepted']} transcripts, runs {len(idx['run_ids_seen'])}")
why = D.index_staleness(idx, data / "predictions", data / "roster/final.json",
                        [data / "transcripts_open", data / "transcripts_web"])
if why and "lacks" in why:
    print(why)
    raise SystemExit("REFUSING: refresh the production index before publication")
if why:
    print(f"STALE: {why}; re-run aggregate_predictions.py and commit the index")
    raise SystemExit("REFUSING: stale production index")
print(f"current: index matches disk ({idx['files_read']} files, {idx['records_read']} records, "
      f"inputs sha256 {idx['inputs_sha256'][:12]})")
scores = data / "predictions/scores.json"
if scores.exists():
    config = data / "predictions/scoring.json"
    if not config.exists():
        raise SystemExit("REFUSING: scores.json has no predictions/scoring.json beside it, so its inputs "
                         "cannot be checked; commit the scoring config and regenerate scores.json from it")
    why = D.scores_staleness(scores, config)
    if why:
        print(f"STALE scores: {why}")
        raise SystemExit("REFUSING: stale scores.json; re-run score_predictions.py --config and commit it")
    print("current: scores.json matches its config and inputs")
    # Current is not enough: a board with rows dropped as stale sidecars would
    # publish those drops without anyone choosing them (critique 3 A5).
    for note in D.scores_review_notes(json.load(scores.open())):
        print(note)
    blockers = D.scores_blockers(json.load(scores.open()))
    if blockers:
        print("; ".join(blockers))
        raise SystemExit("REFUSING: scores.json carries rows it could not score for a reason that must be "
                         "cleared before publication")
    # Operator rule 2026-09-27: the as-of always moves up when predictions are added.
    as_of = json.load(config.open())["as_of"]
    why = D.scores_asof_lag(data, sys.argv[2], as_of)
    if why:
        print(why)
        raise SystemExit("REFUSING: scores as-of is behind the predictions data")
    print(f"current: scores as-of {as_of} is not behind the predictions data")
EOF

check_publication_unchanged

# The page's own provenance, served no-store (site-predictions/_headers) so the
# next deploy can refuse to replace a newer page with an older one.
$PY -c 'import json, sys; json.dump({"data_revision": sys.argv[1], "public_revision": sys.argv[2], "data_date": sys.argv[3]}, open("site-predictions/revision.json", "w"), indent=1, sort_keys=True)' \
  "$DATA_REVISION" "$PUBLIC_REVISION" "$DATA_DATE"
check_origin_before_publish

if [ "$DRY" -eq 1 ]; then
  echo "--dry-run: rendered site-predictions/index.html, published nothing"
  exit 0
fi
npx wrangler deploy -c wrangler.predictions.toml
