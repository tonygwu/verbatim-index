#!/usr/bin/env bash
# Sourced by both deployment entry points after cd to the public repository.
# Publication always names the registered live checkout and its current commit.
PRODUCTION_DATA=""
DATA_REVISION=""
DRY=0
REFRESH=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --production-data|--data-revision)
      [ "$#" -ge 2 ] || { echo "REFUSING: $1 needs a value" >&2; exit 2; }
      if [ "$1" = "--production-data" ]; then PRODUCTION_DATA="$2"; else DATA_REVISION="$2"; fi
      shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --refresh) REFRESH=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
PRODUCTION_DATA="$($PY scripts/data_clone_workflow.py publication-source \
  --production-data "${PRODUCTION_DATA:-.}" --data-revision "$DATA_REVISION")" || exit 1
# --refresh writes only through the owner's own production data symlink.
if [ "$REFRESH" -eq 1 ] && [ "$(cd data && pwd -P)" != "$PRODUCTION_DATA" ]; then
  echo "REFUSING: --refresh requires the production owner's data checkout" >&2
  exit 1
fi
publication_fingerprint() {
  $PY scripts/data_clone_workflow.py publication-source \
    --production-data "$PRODUCTION_DATA" --data-revision "$DATA_REVISION" \
    --site "$PUBLICATION_SITE" --fingerprint
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
