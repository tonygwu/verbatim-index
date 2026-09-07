#!/usr/bin/env bash
# Standalone transcript-fetching daemon. Does nothing but accumulate transcripts.
#
# Deliberately knows nothing about grading, aggregation or rendering. Fetching is
# gated by an external rate limit that flickers on and off for hours, while
# grading is gated by model quota. Chaining them meant one stall blocked the
# other and a grading failure looked like a fetch failure. They are now separate
# processes that share only the files on disk.
#
# The loop is opportunistic: every cycle it fetches whatever it can, and when
# YouTube pushes back it widens its own interval and tries again later. It exits
# on its own once every leader has TARGET transcripts.
#
#   nohup bash scripts/fetch_loop.sh > data/logs/fetch_loop.log 2>&1 &
#
# Safe to kill and restart at any moment. Completed transcripts are skipped.
set -uo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
TARGET="${TARGET:-5}"                 # transcripts wanted per leader
MIN_ACCEPT="${MIN_ACCEPT:-3}"         # below this a leader is reported as thin
PROBE_VIDEO="${PROBE_VIDEO:-93piVCwqXz8}"
# Pacing is deliberately AGGRESSIVE. The operator can rotate the VPN exit on
# demand, so a block costs one manual switch rather than hours of waiting. That
# inverts the economics: a 10s pace was right when an IP was irreplaceable, and
# wasteful once it is not. Fetch fast, trip early, ask for a new IP.
BASE_SLEEP="${BASE_SLEEP:-120}"       # 2 min between productive cycles
MAX_SLEEP="${MAX_SLEEP:-900}"         # 15 min ceiling; the fix is a new IP, not patience
PROBE_EVERY="${PROBE_EVERY:-60}"      # re-probe every minute so a rotation is seen fast
PACE="${PACE:-2}"                     # seconds between caption requests
WORKERS="${WORKERS:-6}"
STATE=data/logs/fetch_loop_state.jsonl
ROTATE_FLAG=data/logs/NEEDS_IP_ROTATION

stamp(){ date -u +%Y-%m-%dT%H:%M:%SZ; }
say(){ printf '[%s] %s\n' "$(stamp)" "$*"; }

# Coverage straight off the filesystem, so restarting the loop costs nothing.
coverage(){
  $PY - "$TARGET" <<'PYEOF'
import json, sys
from pathlib import Path
target = int(sys.argv[1])
roster = [r["slug"] for r in json.loads(Path("data/roster/final.json").read_text())["roster"]]
counts = {s: len(list((Path("data/transcripts") / s).glob("*.json"))) for s in roster}
done = sum(1 for v in counts.values() if v >= target)
print(json.dumps({
    "leaders": len(roster),
    "transcripts": sum(counts.values()),
    "leaders_at_target": done,
    "leaders_with_zero": [s for s, v in counts.items() if v == 0],
    "thin": {s: v for s, v in sorted(counts.items()) if 0 < v < target},
}))
PYEOF
}

# Probe with fetch(), never list(). They are different endpoints with separate
# limits: list() returned OK while fetch() was still blocked, and trusting that
# reading produced a false all-clear and a wasted run.
probe(){
  $PY - "$PROBE_VIDEO" <<'PYEOF'
import sys
from youtube_transcript_api import YouTubeTranscriptApi
try:
    lst = YouTubeTranscriptApi().list(sys.argv[1])
    try:
        tr = lst.find_manually_created_transcript(["en", "en-US", "en-GB"])
    except Exception:
        tr = lst.find_generated_transcript(["en", "en-US", "en-GB"])
    tr.fetch()
    print("CLEAR"); sys.exit(0)
except Exception as exc:
    print(f"BLOCKED {type(exc).__name__}"); sys.exit(1)
PYEOF
}

sleep_for=$BASE_SLEEP
cycle=0
say "fetch loop started. target ${TARGET}/leader, pace ${PACE}s, ${WORKERS} workers"

while true; do
  cycle=$((cycle + 1))
  cov="$(coverage)"
  at_target=$($PY -c "import json,sys;print(json.loads(sys.argv[1])['leaders_at_target'])" "$cov")
  total=$($PY -c "import json,sys;print(json.loads(sys.argv[1])['transcripts'])" "$cov")
  n_leaders=$($PY -c "import json,sys;print(json.loads(sys.argv[1])['leaders'])" "$cov")

  if [ "$at_target" -ge "$n_leaders" ]; then
    say "COMPLETE: all ${n_leaders} leaders have ${TARGET} transcripts (${total} total). exiting."
    printf '{"at":"%s","event":"complete","transcripts":%s}\n' "$(stamp)" "$total" >> "$STATE"
    exit 0
  fi

  say "cycle ${cycle}: ${total} transcripts, ${at_target}/${n_leaders} leaders at target"

  if ! probe >/dev/null 2>&1; then
    sleep_for=$(( sleep_for * 2 )); [ "$sleep_for" -gt "$MAX_SLEEP" ] && sleep_for=$MAX_SLEEP
    ip=$(curl -sS --max-time 8 https://api.ipify.org 2>/dev/null || echo unknown)
    printf '%s\n' "$(stamp) blocked on IP $ip" > "$ROTATE_FLAG"
    say "  ############################################################"
    say "  #  BLOCKED on IP ${ip}"
    say "  #  ROTATE THE VPN TO A NEW EXIT. The loop re-probes every ${PROBE_EVERY}s"
    say "  #  and resumes automatically the moment a new IP works."
    say "  ############################################################"
    printf '{"at":"%s","cycle":%s,"event":"blocked","sleep":%s}\n' "$(stamp)" "$cycle" "$sleep_for" >> "$STATE"
    # Poll THROUGH the backoff rather than sleeping it out. Measured over one
    # night: 10 blocked cycles to 1 productive one, because a 90 minute sleep
    # kept missing windows that reopened within minutes. A single probe is one
    # request, so watching costs almost nothing next to what it recovers.
    waited=0
    while [ "$waited" -lt "$sleep_for" ]; do
      sleep "$PROBE_EVERY"
      waited=$(( waited + PROBE_EVERY ))
      if probe >/dev/null 2>&1; then
        rm -f "$ROTATE_FLAG"
        newip=$(curl -sS --max-time 8 https://api.ipify.org 2>/dev/null || echo unknown)
        say "  RESUMED after ${waited}s on IP ${newip}"
        printf '{"at":"%s","cycle":%s,"event":"early_clear","after":%s}\n' "$(stamp)" "$cycle" "$waited" >> "$STATE"
        sleep_for=$BASE_SLEEP
        break
      fi
    done
    continue
  fi

  rm -f "$ROTATE_FLAG"
  before=$(find data/transcripts -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
  say "  endpoint clear. fetching at ${PACE}s pace, ${WORKERS} workers."
  $PY scripts/fetch_transcripts.py \
    --manifest data/sources/all.jsonl \
    --out data/transcripts \
    --errors "data/logs/fetch_errors_cycle${cycle}.jsonl" \
    --workers "$WORKERS" --target-per-leader "$TARGET" --min-interval "$PACE" \
    >/dev/null 2>>data/logs/fetch_loop.err
  after=$(find data/transcripts -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
  gained=$(( after - before ))

  printf '{"at":"%s","cycle":%s,"event":"pass","gained":%s,"total":%s}\n' \
    "$(stamp)" "$cycle" "$gained" "$after" >> "$STATE"

  # Make what we just fetched grade-ready immediately. normalize used to run
  # only at the top of a grade_loop cycle, and a cycle is hours long because it
  # grades everything available, so newly fetched transcripts sat unusable for
  # hours: measured 203 fetched against 66 blinded. QA and normalize are cheap
  # and idempotent, so running them here decouples grade-readiness from the
  # slow grading pass.
  if [ "$gained" -gt 0 ]; then
    $PY scripts/qa_transcripts.py --transcripts data/transcripts \
        --roster data/roster/final.json --glossaries data/sources/aliases.json \
        --out data/logs/transcript_qa.json >/dev/null 2>>data/logs/fetch_loop.err
    for m in blinded open; do
      out=data/transcripts_blind; [ "$m" = open ] && out=data/transcripts_open
      $PY scripts/normalize_transcripts.py --mode "$m" \
          --transcripts data/transcripts --out "$out" \
          --roster data/roster/final.json --repairs data/sources/repairs.json \
          --aliases data/sources/aliases.json --qa data/logs/transcript_qa.json \
        --grades data/grades \
          --log "data/logs/normalize_${m}.json" >/dev/null 2>>data/logs/fetch_loop.err
    done
    say "  normalized; $(find data/transcripts_blind -name '*.json' ! -name '*.tmp' | wc -l | tr -d ' ') ready to grade"
  fi

  if [ "$gained" -gt 0 ]; then
    sleep_for=$BASE_SLEEP           # it worked, go back to the normal cadence
    say "  +${gained} transcripts (now ${after}). sleeping ${sleep_for}s"
  else
    sleep_for=$(( sleep_for * 2 )); [ "$sleep_for" -gt "$MAX_SLEEP" ] && sleep_for=$MAX_SLEEP
    say "  no new transcripts this pass. sleeping ${sleep_for}s"
  fi
  sleep "$sleep_for"
done
