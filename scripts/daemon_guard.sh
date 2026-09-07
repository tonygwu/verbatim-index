#!/usr/bin/env bash
# Refuse to run a daemon anywhere but the clone that owns data/.
#
# Every clone's data/ is a symlink to one shared checkout, so a loop started in
# the wrong clone no longer scribbles on a private copy. It writes the live
# corpus, which is the only irreplaceable thing here. Before the share this was
# a line in CLAUDE.md; it has to be a failing precondition now.
#
# The marker lives in the shared checkout and is gitignored there, because it
# names one machine's local clone and there is only one checkout to hold it.
#
# Usage, after the script has cd'd to its own repo root:
#   . scripts/daemon_guard.sh
#   require_daemon_clone || exit 1
require_daemon_clone() {
  local marker="data/.daemon-clone" here owner
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
    echo "  All clones share one data/ checkout, so a loop here writes the live" >&2
    echo "  corpus. Start it in '$owner', or change the marker if the daemons moved." >&2
    return 1
  fi
}
