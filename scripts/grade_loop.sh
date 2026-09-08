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
#   sweep            retires duplicate appearances before they are graded
#   qa + normalize   cheap, re-runs over everything; withdraws what left the shelf
#   grade            skips any (transcript, judge, mode) already on disk
#   aggregate+render cheap, gives an always-current leaderboard
#
#   nohup bash scripts/grade_loop.sh > data/logs/grade_loop.log 2>&1 &
set -uo pipefail
cd "$(dirname "$0")/.."

# Every clone shares one data/ checkout, so a loop started in the wrong clone
# writes the live corpus rather than a private copy.
. scripts/daemon_guard.sh
require_daemon_clone || exit 1

PY=.venv/bin/python
WORKERS="${WORKERS:-8}"
# Which judges the blinded pass runs. Default is unchanged, so adding the
# Gemini arm is an explicit act rather than something a restart picks up.
#
# The Gemini backfill is a bounded one-time job over the existing corpus and is
# better run on its own (see AGENTS.md), because Antigravity quota cannot be
# measured: mixing it into the loop makes a quota stop harder to attribute to
# the arm that caused it. Once the backfill is complete and the arm is promoted
# out of SHADOW_JUDGES, set BLIND_JUDGES=fable,astra,gemini here so NEW
# transcripts keep the judge mix even.
BLIND_JUDGES="${BLIND_JUDGES:-fable,astra}"
OPEN_PER_LEADER="${OPEN_PER_LEADER:-2}"
CYCLE_SLEEP="${CYCLE_SLEEP:-300}"
FABLE_ACCOUNTS="${FABLE_ACCOUNTS:-}"  # pin Fable to named accounts, e.g. "default"
MIN_TO_START="${MIN_TO_START:-4}"      # do not spin up the expensive stage for 1 file
IDLE_EXIT="${IDLE_EXIT:-3}"            # consecutive no-op cycles with fetch gone -> stop

stamp(){ date -u +%Y-%m-%dT%H:%M:%SZ; }
say(){ printf '[%s] %s\n' "$(stamp)" "$*"; }
count_tx(){ find data/transcripts -name '*.json' ! -name '*.tmp' 2>/dev/null | wc -l | tr -d ' '; }
count_grades(){ find data/grades -name '*.json' ! -name '*.tmp' -not -path '*/_raw/*' 2>/dev/null | wc -l | tr -d ' '; }

idle=0
cycle=0
say "grade loop started. ${WORKERS} workers, blinded judges ${BLIND_JUDGES}, unblinded on ${OPEN_PER_LEADER}/leader"
[ -n "$FABLE_ACCOUNTS" ] && say "  Fable pinned to accounts: ${FABLE_ACCOUNTS}"

while true; do
  cycle=$((cycle + 1))
  tx=$(count_tx)
  g0=$(count_grades)

  if [ "${tx:-0}" -lt "$MIN_TO_START" ]; then
    say "cycle ${cycle}: only ${tx} transcripts, waiting for at least ${MIN_TO_START}"
    sleep "$CYCLE_SLEEP"; continue
  fi

  say "cycle ${cycle}: ${tx} transcripts, ${g0} grades on disk"

  # 1. Take duplicates off the shelf BEFORE anything is copied for grading.
  #    Most duplicates are one talk re-uploaded to several YouTube channels, and
  #    those arrive through fetch_loop.sh. The sweep used to run only in
  #    happyscribe_loop.sh, which adds nothing to YouTube's side of the corpus,
  #    so a re-upload was routinely graded before the next sweep saw it. On
  #    2026-09-07 the corpus held 16 duplicates the sweep would have retired.
  say "  sweeping the corpus for duplicate appearances"
  if $PY scripts/dedupe_transcripts.py --sweep --grades data/grades \
       --out data/logs/dedupe_sweep_pass.json \
       >data/logs/dedupe_sweep.json 2>>data/logs/grade_loop.err; then
    cat data/logs/dedupe_sweep.json >> data/logs/dedupe_sweep.log
    say "  $($PY -c "import json; d=json.load(open('data/logs/dedupe_sweep.json')); print(f\"retired {d['sweep_retired']} duplicates, orphaned {d['orphaned_grades_removed']} grades\")" 2>/dev/null || echo 'sweep report unreadable')"
  else
    say "  SWEEP FAILED, nothing retired this cycle; see data/logs/grade_loop.err"
  fi

  # 2. Quality gates, then blind and un-blind. Both re-run over everything and
  #    are cheap; a transcript rejected by QA never reaches the graders.
  #    --grades lets normalize withdraw the grades of a transcript that has left
  #    the corpus. Without it the appearance keeps scoring, because aggregate.py
  #    reads data/grades and never looks at the blinded directory.
  $PY scripts/qa_transcripts.py --transcripts data/transcripts \
      --roster data/roster/final.json --glossaries data/sources/aliases.json \
      --out data/logs/transcript_qa.json > /dev/null 2>>data/logs/grade_loop.err
  norm_ok=1
  for mode in blinded open; do
    out=data/transcripts_blind; [ "$mode" = open ] && out=data/transcripts_open
    if ! $PY scripts/normalize_transcripts.py --mode "$mode" \
        --transcripts data/transcripts --out "$out" \
        --roster data/roster/final.json --repairs data/sources/repairs.json \
        --aliases data/sources/aliases.json --qa data/logs/transcript_qa.json \
        --grades data/grades \
        --log "data/logs/normalize_${mode}.json" > /dev/null 2>>data/logs/grade_loop.err; then
      norm_ok=0
      say "  NORMALIZE FAILED for ${mode}; see data/logs/grade_loop.err and data/logs/normalize_${mode}.json"
    fi
  done
  if [ "$norm_ok" -eq 0 ]; then
    # The commonest cause is the prune refusing, which means the corpus looks
    # wrong rather than smaller. Grading an unpruned directory would re-grade
    # whatever should have been withdrawn, so wait a cycle instead.
    say "  skipping this cycle's grading because normalize did not complete"
    sleep "$CYCLE_SLEEP"; continue
  fi
  ready=$(find data/transcripts_blind -name '*.json' ! -name '*.tmp' 2>/dev/null | wc -l | tr -d ' ')
  say "  ${ready} transcripts passed QA and are ready to grade"

  # 3. Blinded grading. This is the published score, so it covers everything.
  say "  blinded grading pass"
  $PY scripts/grade.py --transcripts data/transcripts_blind --roster data/roster/final.json \
      --out data/grades --judges "$BLIND_JUDGES" --modes blinded --repeats 1 \
      --workers "$WORKERS" --errors data/logs/grade_errors_blind.jsonl --timeout 2400 \
      --fable-accounts "$FABLE_ACCOUNTS" \
      >> data/logs/grade_loop.out 2>>data/logs/grade_loop.err

  # 4. Unblinded, on a bounded subset. Only needed to size the reputation halo,
  #    so it must stay small: it competes with the blinded pass for the same
  #    Fable quota, and the blinded pass is the published score.
  if [ "${OPEN_PER_LEADER:-0}" -eq 0 ]; then
    say "  unblinded grading pass SKIPPED (OPEN_PER_LEADER=0)"
  else
    say "  unblinded grading pass (${OPEN_PER_LEADER}/leader)"
    $PY scripts/grade.py --transcripts data/transcripts_open --roster data/roster/final.json \
        --out data/grades --judges fable,astra --modes open --repeats 1 \
        --limit-per-leader "$OPEN_PER_LEADER" \
        --workers "$WORKERS" --errors data/logs/grade_errors_open.jsonl --timeout 2400 \
        --fable-accounts "$FABLE_ACCOUNTS" \
        >> data/logs/grade_loop.out 2>>data/logs/grade_loop.err
  fi

  # 5. Always leave a current leaderboard behind, even mid-run.
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
