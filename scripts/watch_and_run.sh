#!/usr/bin/env bash
# Wait for YouTube's caption endpoint to unblock, then run the whole pipeline.
#
# Probes with fetch(), never list(). They are different endpoints: list() came
# back OK while fetch() was still IpBlocked, and trusting that probe cost a
# false "unblocked" call. One probe per cycle, so the watcher itself cannot be
# what keeps the block alive.
#
# Everything downstream is resumable, so this is safe to kill and restart at any
# point. Completed transcripts and completed judge calls are skipped.
#
#   nohup setsid scripts/watch_and_run.sh > data/logs/watch.log 2>&1 &
set -uo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
PROBE_VIDEO="${PROBE_VIDEO:-93piVCwqXz8}"
INTERVAL="${INTERVAL:-1800}"          # 30 minutes between probes
MAX_CYCLES="${MAX_CYCLES:-96}"        # 48 hours, then give up and say so
STATE=data/logs/watch_state.jsonl

stamp(){ date -u +%Y-%m-%dT%H:%M:%SZ; }
say(){ printf '[%s] %s\n' "$(stamp)" "$*"; }

probe(){
  $PY - "$PROBE_VIDEO" <<'PYEOF'
import sys
from youtube_transcript_api import YouTubeTranscriptApi
vid = sys.argv[1]
try:
    lst = YouTubeTranscriptApi().list(vid)
    try:
        tr = lst.find_manually_created_transcript(["en", "en-US", "en-GB"])
    except Exception:
        tr = lst.find_generated_transcript(["en", "en-US", "en-GB"])
    data = tr.fetch()          # the endpoint that was actually blocked
    print(f"CLEAR {len(data)}")
    sys.exit(0)
except Exception as exc:
    print(f"BLOCKED {type(exc).__name__}")
    sys.exit(1)
PYEOF
}

say "watcher started. probing fetch() every ${INTERVAL}s, up to ${MAX_CYCLES} cycles"
for ((i=1; i<=MAX_CYCLES; i++)); do
  out="$(probe)"; rc=$?
  printf '{"at":"%s","cycle":%s,"result":"%s"}\n' "$(stamp)" "$i" "$out" >> "$STATE"
  if [ $rc -eq 0 ]; then
    say "UNBLOCKED on cycle $i ($out). starting pipeline."
    break
  fi
  say "cycle $i/$MAX_CYCLES: $out. sleeping ${INTERVAL}s"
  [ "$i" -eq "$MAX_CYCLES" ] && { say "gave up after $MAX_CYCLES cycles; still blocked"; exit 1; }
  sleep "$INTERVAL"
done

# Ramp in gently. The block came back instantly last time on a 6s pacer, so the
# first pass runs slower and only takes 3 transcripts per leader. A second pass
# tops up to 5 once the first has proven the pace holds.
say "=== stage 2a: fetch, slow pass, 3 per leader at 12s ==="
$PY scripts/fetch_transcripts.py --manifest data/sources/all.jsonl \
  --out data/transcripts --errors data/logs/fetch_errors_pass1.jsonl \
  --workers 3 --target-per-leader 3 --min-interval 12
rc1=$?
say "slow pass exit=$rc1; transcripts on disk: $(find data/transcripts -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"

say "=== stage 2b: fetch, top-up to 5 per leader at 8s ==="
$PY scripts/fetch_transcripts.py --manifest data/sources/all.jsonl \
  --out data/transcripts --errors data/logs/fetch_errors_pass2.jsonl \
  --workers 4 --target-per-leader 5 --min-interval 8
say "top-up done; transcripts on disk: $(find data/transcripts -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"

n=$(find data/transcripts -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
if [ "${n:-0}" -lt 40 ]; then
  say "only $n transcripts fetched; too few to score 40 leaders. stopping before the expensive stage."
  exit 1
fi

say "=== stages 3-8: qa, normalize, grade, aggregate, render ==="
STAGES="3 4 5 6 7 8" WORKERS=10 bash scripts/run_pipeline.sh
say "pipeline finished. leaderboard: site/index.html"
