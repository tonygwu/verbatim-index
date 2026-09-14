#!/usr/bin/env bash
# Only the production owner may run daemons or production aggregation.
# Experiment role lives in the private clone's local Git config.
#
# The checkout is the study's own: $DATA as scripts/study_env.sh sets it, and
# `data` when that was not sourced. Two studies share this engine, so before
# asking who owns a checkout this asks whose checkout it is:
#   - a .study marker must name $STUDY (default leaders);
#   - a checkout WITHOUT a marker is leaders, and only leaders;
#   - any other study also needs its checkout's origin to be verbatim-<study>-data.
# These restate scripts/study_profile.py, whose load() refuses a profile that
# disagrees, so a loop refuses before any Python stage is reached.
require_daemon_clone() {
  local data="${DATA:-data}" study="${STUDY:-leaders}" marker here owner found origin
  marker="$data/.daemon-clone"
  found=""
  [ -f "$data/.study" ] && found="$(tr -d '[:space:]' < "$data/.study")"
  if [ -n "$found" ] && [ "$found" != "$study" ]; then
    echo "REFUSING TO START: $data/.study names '$found', but this is the '$study' study." >&2
    return 1
  fi
  if [ "$study" != "leaders" ]; then
    if [ -z "$found" ]; then
      echo "REFUSING TO START: $data has no .study naming '$study', so it is not this study's checkout." >&2
      return 1
    fi
    origin="$(git -C "$data" config --get remote.origin.url 2>/dev/null || true)"
    origin="${origin%/}"
    origin="${origin##*[/:]}"
    origin="${origin%.git}"
    if [ "$origin" != "verbatim-$study-data" ]; then
      echo "REFUSING TO START: $data has origin '$origin'; the '$study' study requires 'verbatim-$study-data'." >&2
      return 1
    fi
  fi
  if [ "$(git -C "$data" config --local --get verbatim.role 2>/dev/null || true)" = "experiment" ]; then
    echo "REFUSING TO START: experiment data cannot run production jobs." >&2
    return 1
  fi
  here="$(basename "$(pwd -P)")"
  if [ ! -f "$marker" ]; then
    echo "REFUSING TO START: $marker is missing. It must name the clone that runs" >&2
    echo "  the daemons, e.g. 'echo repo-0 > $marker'. Without it a loop started in" >&2
    echo "  the wrong clone would write the shared live corpus." >&2
    return 1
  fi
  owner="$(tr -d '[:space:]' < "$marker")"
  if [ "$here" != "$owner" ]; then
    echo "REFUSING TO START: this clone is '$here' but $marker names '$owner'." >&2
    echo "  This $data/ checkout belongs to the production owner; a loop writes the live" >&2
    echo "  corpus. Start it in '$owner', or change the marker if the daemons moved." >&2
    return 1
  fi
}
