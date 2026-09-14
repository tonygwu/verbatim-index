#!/usr/bin/env bash
# Which study a loop belongs to, and where that study's data lives.
#
# Sourced by the loops right after they cd to the repo root, BEFORE
# daemon_guard.sh and run_marker.sh, because both read what this sets:
#
#   . scripts/study_env.sh || exit 1
#
# STUDY defaults to leaders, so every existing leaders command line runs
# unchanged. The link rule is the one scripts/study_profile.py enforces on the
# profile: leaders -> data, any other study -> data-<study>. An unknown study
# has no profiles/<study>.json and is refused here rather than falling back.
#
# RUN_MARKER_DIR moves under the study's own data. A shared marker directory
# would let a leaders grade loop see a pundits fetcher as "still running", and
# the reverse. An explicit RUN_MARKER_DIR is still honoured, as the marker
# tests rely on.

STUDY="${STUDY:-leaders}"
case "$STUDY" in
  ''|-*|*[!a-z0-9-]*)
    echo "REFUSING TO START: STUDY must be lowercase letters, digits and '-', got '$STUDY'." >&2
    return 1 ;;
esac
if [ ! -f "profiles/$STUDY.json" ]; then
  echo "REFUSING TO START: unknown study '$STUDY'; there is no profiles/$STUDY.json." >&2
  return 1
fi
if [ "$STUDY" = leaders ]; then
  DATA=data
  SITE_DIR=site
else
  DATA="data-$STUDY"
  SITE_DIR="site-$STUDY"
fi
RUN_MARKER_DIR="${RUN_MARKER_DIR:-$DATA/logs/running}"
export STUDY DATA SITE_DIR RUN_MARKER_DIR
