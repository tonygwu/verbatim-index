#!/usr/bin/env bash
# Sourced by both deployment entry points after cd to the public repository.
# Publication always names the registered live checkout and its current commit.
PRODUCTION_DATA=""
DATA_REVISION=""
DRY=0
REFRESH=0
FIRST_REVISION=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --production-data|--data-revision)
      [ "$#" -ge 2 ] || { echo "REFUSING: $1 needs a value" >&2; exit 2; }
      if [ "$1" = "--production-data" ]; then PRODUCTION_DATA="$2"; else DATA_REVISION="$2"; fi
      shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --refresh) REFRESH=1; shift ;;
    --first-revision-deploy) FIRST_REVISION=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
# Origin mode (the predictions site): any push-role clone publishes exactly
# origin/main. Owner mode (everything else): the daemon clone's checkout.
ORIGIN_FLAG=()
if [ "${PUBLICATION_MODE:-owner}" = "origin" ]; then
  if [ "$REFRESH" -eq 1 ]; then
    echo "REFUSING: --refresh was removed from this site; regenerate derived files with scripts/data_sync.py push, then deploy" >&2
    exit 2
  fi
  ORIGIN_FLAG=(--origin --site "$PUBLICATION_SITE")
fi
PRODUCTION_DATA="$($PY scripts/data_clone_workflow.py publication-source \
  --production-data "${PRODUCTION_DATA:-.}" --data-revision "$DATA_REVISION" \
  ${ORIGIN_FLAG[@]+"${ORIGIN_FLAG[@]}"})" || exit 1
# Origin mode only; owner-mode sites may render from a public tree that is not
# a git checkout at all, as their tests do.
PUBLIC_REVISION=""
if [ "${PUBLICATION_MODE:-owner}" = "origin" ]; then
  PUBLIC_REVISION="$(git rev-parse HEAD)"
fi
# --refresh writes only through the owner's own production data symlink. That is
# the study's own link: $DATA from scripts/study_env.sh, and `data` for leaders.
if [ "$REFRESH" -eq 1 ] && [ "$(cd "${DATA:-data}" && pwd -P)" != "$PRODUCTION_DATA" ]; then
  echo "REFUSING: --refresh requires the production owner's data checkout" >&2
  exit 1
fi
publication_fingerprint() {
  if [ "${PUBLICATION_MODE:-owner}" = "origin" ]; then
    $PY scripts/data_clone_workflow.py publication-source \
      --production-data "$PRODUCTION_DATA" --data-revision "$DATA_REVISION" \
      --site "$PUBLICATION_SITE" --fingerprint --origin
  else
    $PY scripts/data_clone_workflow.py publication-source \
      --production-data "$PRODUCTION_DATA" --data-revision "$DATA_REVISION" \
      --site "$PUBLICATION_SITE" --fingerprint
  fi
}
check_publication_unchanged() {
  local after
  after="$(publication_fingerprint)" || return 1
  if [ "$after" != "$PUBLICATION_BEFORE" ]; then
    echo "REFUSING: production data changed during rendering; render again from the new revision" >&2
    return 1
  fi
  echo "production source: $PRODUCTION_DATA at $DATA_REVISION; content sha256 $after"
}
# Origin mode only: nothing moved on either remote while the page rendered, and
# the live page is not newer than this one (wrangler is last-writer-wins).
check_origin_before_publish() {
  $PY scripts/data_clone_workflow.py origin-unmoved --production-data "$PRODUCTION_DATA" \
    --data-revision "$DATA_REVISION" --public-revision "$PUBLIC_REVISION" || return 1
  local first=()
  [ "$FIRST_REVISION" -eq 1 ] && first=(--first-revision-deploy)
  $PY scripts/data_clone_workflow.py live-revision --production-data "$PRODUCTION_DATA" \
    --data-revision "$DATA_REVISION" ${first[@]+"${first[@]}"} || return 1
  echo "origin unmoved and the live page is not newer: data $DATA_REVISION, public $PUBLIC_REVISION"
}
