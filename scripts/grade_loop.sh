#!/usr/bin/env bash
# Grading daemon. Grades whatever transcripts exist right now, then re-renders
# the leaderboard, then looks again for new ones.
#
# Runs concurrently with fetch_loop.sh and shares nothing with it but files.
# That is the point: fetching is gated by YouTube's rate limit and grading by
# model quota, and neither should be able to stall the other. Waiting for the
# full corpus before grading would idle the expensive stage for hours while
# transcripts trickle in.
#
# Every stage is idempotent and skips completed work, so each cycle only pays
# for what is genuinely new:
#   qa + normalize   cheap, re-runs over everything
#   grade            skips any (transcript, judge, mode) already on disk
#   aggregate+render cheap, gives an always-current leaderboard
#
#   nohup bash scripts/grade_loop.sh > data/logs/grade_loop.log 2>&1 &
set -uo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
WORKERS="${WORKERS:-8}"
OPEN_PER_LEADER="${OPEN_PER_LEADER:-2}"
CYCLE_SLEEP="${CYCLE_SLEEP:-300}"
MIN_TO_START="${MIN_TO_START:-4}"      # do not spin up the expensive stage for 1 file
IDLE_EXIT="${IDLE_EXIT:-3}"            # consecutive no-op cycles with fetch gone -> stop

stamp(){ date -u +%Y-%m-%dT%H:%M:%SZ; }
say(){ printf '[%s] %s\n' "$(stamp)" "$*"; }
count_tx(){ find data/transcripts -name '*.json' ! -name '*.tmp' 2>/dev/null | wc -l | tr -d ' '; }
count_grades(){ find data/grades -name '*.json' ! -name '*.tmp' -not -path '*/_raw/*' 2>/dev/null | wc -l | tr -d ' '; }

idle=0
cycle=0
say "grade loop started. ${WORKERS} workers, unblinded on ${OPEN_PER_LEADER}/leader"

while true; do
  cycle=$((cycle + 1))
  tx=$(count_tx)
  g0=$(count_grades)

  if [ "${tx:-0}" -lt "$MIN_TO_START" ]; then
    say "cycle ${cycle}: only ${tx} transcripts, waiting for at least ${MIN_TO_START}"
    sleep "$CYCLE_SLEEP"; continue
  fi

  say "cycle ${cycle}: ${tx} transcripts, ${g0} grades on disk"

  # 1. Quality gates, then blind and un-blind. Both re-run over everything and
  #    are cheap; a transcript rejected by QA never reaches the graders.
  $PY scripts/qa_transcripts.py --transcripts data/transcripts \
      --roster data/roster/final.json --glossaries data/sources/aliases.json \
      --out data/logs/transcript_qa.json > /dev/null 2>>data/logs/grade_loop.err
  for mode in blinded open; do
    out=data/transcripts_blind; [ "$mode" = open ] && out=data/transcripts_open
    $PY scripts/normalize_transcripts.py --mode "$mode" \
        --transcripts data/transcripts --out "$out" \
        --roster data/roster/final.json --repairs data/sources/repairs.json \
        --aliases data/sources/aliases.json --qa data/logs/transcript_qa.json \
        --log "data/logs/normalize_${mode}.json" > /dev/null 2>>data/logs/grade_loop.err
  done
  ready=$(find data/transcripts_blind -name '*.json' ! -name '*.tmp' 2>/dev/null | wc -l | tr -d ' ')
  say "  ${ready} transcripts passed QA and are ready to grade"

  # 2. Blinded grading. This is the published score, so it covers everything.
  say "  blinded grading pass"
  $PY scripts/grade.py --transcripts data/transcripts_blind --roster data/roster/final.json \
      --out data/grades --judges fable,astra --modes blinded --repeats 1 \
      --workers "$WORKERS" --errors data/logs/grade_errors_blind.jsonl --timeout 2400 \
      >> data/logs/grade_loop.out 2>>data/logs/grade_loop.err

  # 3. Unblinded, on a bounded subset. Only needed to size the reputation halo.
  say "  unblinded grading pass (${OPEN_PER_LEADER}/leader)"
  $PY scripts/grade.py --transcripts data/transcripts_open --roster data/roster/final.json \
      --out data/grades --judges fable,astra --modes open --repeats 1 \
      --limit-per-leader "$OPEN_PER_LEADER" \
      --workers "$WORKERS" --errors data/logs/grade_errors_open.jsonl --timeout 2400 \
      >> data/logs/grade_loop.out 2>>data/logs/grade_loop.err

  # 4. Always leave a current leaderboard behind, even mid-run.
  $PY scripts/aggregate.py --grades data/grades --roster data/roster/final.json \
      --transcripts data/transcripts_blind --out data/results.json \
      > /dev/null 2>>data/logs/grade_loop.err \
  && $PY scripts/build_site.py --results data/results.json --audit data/results_audit.json \
      --roster data/roster/final.json --calibration data/logs/calibration.json \
      --sources data/sources/discovered.json --out site/index.html \
      >> data/logs/grade_loop.out 2>>data/logs/grade_loop.err \
  && say "  leaderboard re-rendered from $(count_grades) grades"

  g1=$(count_grades)
  gained=$(( g1 - g0 ))
  say "cycle ${cycle} done: +${gained} grades (total ${g1})"

  # Stop only when nothing is arriving AND the fetcher has finished for good.
  if [ "$gained" -eq 0 ]; then
    if pgrep -f "fetch_loop.sh" > /dev/null; then
      say "  no new grades, but fetch loop is still running. waiting."
      idle=0
    else
      idle=$((idle + 1))
      say "  no new grades and no fetcher (${idle}/${IDLE_EXIT})"
      if [ "$idle" -ge "$IDLE_EXIT" ]; then
        say "COMPLETE: nothing left to grade. leaderboard at site/index.html"
        exit 0
      fi
    fi
  else
    idle=0
  fi
  sleep "$CYCLE_SLEEP"
done
