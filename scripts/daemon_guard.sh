#!/usr/bin/env bash
# Only the production owner may run daemons or production aggregation.
# Experiment role lives in the private clone's local Git config.
require_daemon_clone() {
  local marker="data/.daemon-clone" here owner
  if [ "$(git -C data config --local --get verbatim.role 2>/dev/null || true)" = "experiment" ]; then
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
    echo "  This data/ checkout belongs to the production owner; a loop writes the live" >&2
    echo "  corpus. Start it in '$owner', or change the marker if the daemons moved." >&2
    return 1
  fi
}
