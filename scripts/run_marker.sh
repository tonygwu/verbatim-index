#!/usr/bin/env bash
# Run markers: how a transcript source tells grade_loop.sh that it is running.
#
# A fetch loop CLAIMS a marker when it starts and removes it when it exits.
# grade_loop.sh asks the marker instead of reading the process list. The
# process-list version answered "no source running" on 2026-09-11 at 07:49:51Z
# while happyscribe_loop ran until 08:24:33Z, and it never reproduced, so the
# grader stopped trusting process text.
#
# Measured on this Mac's /bin/bash 3.2 before this was written: the EXIT trap
# runs on a normal exit and on a plain `kill` (SIGTERM), and does NOT run on
# `kill -9`. So a marker can outlive its loop, and "the file exists" is not
# enough. The marker records the loop's pid and that pid's start time, and it
# counts only while the pid is alive, is not a zombie, and still has that start
# time. Pids are reused, and the start time tells two holders of one pid apart.
#
# The start time is read with TZ=UTC. Without it `ps` prints local time, and a
# writer and reader with different TZ settings would disagree about one moment.
# File modification time is never read: it records when a file was touched,
# not who is running.
#
# Usage, after the script has cd'd to its own repo root:
#   . scripts/run_marker.sh
#   claim_run_marker "$(basename "$0")" || exit 1      # in a transcript source
#   run_marker_alive fetch_loop.sh                     # in grade_loop.sh
#
# run_marker_alive returns 0 running, 1 not running, 2 marker unreadable.
# Status 2 is an error for the caller to stop on, never a guess either way.
# Guarded by scripts/test_run_marker.py.

RUN_MARKER_DIR="${RUN_MARKER_DIR:-data/logs/running}"

_run_marker_path() { printf '%s/%s.marker' "$RUN_MARKER_DIR" "$1"; }

_run_marker_field() { sed -n "s/^$2=//p" "$1" | head -1; }

# Start time of a live, non-zombie pid in UTC, trimmed. Empty otherwise.
_run_marker_started() {
  case "$(ps -o stat= -p "$1" 2>/dev/null)" in
    ''|Z*) return 0 ;;
  esac
  TZ=UTC ps -o lstart= -p "$1" 2>/dev/null | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

run_marker_alive() {
  local name="$1" path pid want have
  path="$(_run_marker_path "$name")"
  [ -f "$path" ] || return 1
  pid="$(_run_marker_field "$path" pid)"
  want="$(_run_marker_field "$path" started_utc)"
  case "$pid" in
    ''|*[!0-9]*)
      echo "RUN MARKER UNREADABLE: $path has no numeric pid, so whether $name is running cannot be known." >&2
      return 2 ;;
  esac
  if [ -z "$want" ]; then
    echo "RUN MARKER UNREADABLE: $path has no started_utc, so whether $name is running cannot be known." >&2
    return 2
  fi
  have="$(_run_marker_started "$pid")"
  if [ -z "$have" ]; then
    echo "stale run marker: $path names pid $pid, which is not running. Not counted. Its loop probably got kill -9." >&2
    return 1
  fi
  if [ "$have" != "$want" ]; then
    echo "stale run marker: $path names pid $pid started $want UTC, but pid $pid now started $have UTC. The pid was reused. Not counted." >&2
    return 1
  fi
  return 0
}

claim_run_marker() {
  local name="$1" path tmp started rc
  path="$(_run_marker_path "$name")"
  if ! mkdir -p "$RUN_MARKER_DIR"; then
    echo "REFUSING TO START: cannot create $RUN_MARKER_DIR for the run marker of $name." >&2
    return 1
  fi
  if [ -f "$path" ]; then
    run_marker_alive "$name" 2>/dev/null; rc=$?
    if [ "$rc" -eq 0 ]; then
      echo "REFUSING TO START: $name is already running as pid $(_run_marker_field "$path" pid), per $path. Two copies would fetch into one corpus." >&2
      return 1
    fi
    if [ "$rc" -eq 2 ]; then
      echo "REFUSING TO START: $path is unreadable. Inspect it, and remove it only if no $name is running." >&2
      return 1
    fi
    echo "replacing stale run marker $path: pid $(_run_marker_field "$path" pid) is not running." >&2
    rm -f "$path"
  fi
  started="$(_run_marker_started "$$")"
  if [ -z "$started" ]; then
    echo "REFUSING TO START: cannot read the start time of pid $$ for the run marker of $name." >&2
    return 1
  fi
  # Written in full to a temp file, then hard-linked into place. `ln` fails if
  # the marker already exists, so the claim is atomic and exclusive, and a
  # reader can never see a half-written marker and call it unreadable.
  tmp="$path.tmp.$$"
  if ! printf 'pid=%s\nstarted_utc=%s\n' "$$" "$started" > "$tmp"; then
    rm -f "$tmp"
    echo "REFUSING TO START: cannot write $tmp for the run marker of $name." >&2
    return 1
  fi
  if ! ln "$tmp" "$path" 2>/dev/null; then
    rm -f "$tmp"
    echo "REFUSING TO START: another $name claimed $path at the same moment." >&2
    return 1
  fi
  rm -f "$tmp"
  _RUN_MARKER_NAME="$name"
  trap 'release_run_marker "$_RUN_MARKER_NAME"' EXIT
}

# Remove the marker only if this process wrote it. A second copy that was
# refused, or any other process, must not delete a live loop's marker.
release_run_marker() {
  local path
  path="$(_run_marker_path "$1")"
  [ -f "$path" ] || return 0
  [ "$(_run_marker_field "$path" pid)" = "$$" ] && rm -f "$path"
  return 0
}
