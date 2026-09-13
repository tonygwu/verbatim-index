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
# Which judges the blinded pass runs. All three since 2026-09-08, when the
# Gemini arm was promoted out of SHADOW_JUDGES after backfilling the corpus.
#
# It has to be all three. A leader's score is compared across judges, so a new
# transcript graded by only two would reintroduce exactly the uneven judge MIX
# the backfill existed to remove, and drift it wider every cycle. Set this to
# fable,astra to fall back to two judges if the Antigravity arm has to be pulled.
# Every process that can ADD transcripts to the corpus. This loop must not
# declare grading finished while any of them is still feeding it.
#
# A source counts as running only while it holds a run marker: a small file it
# creates when it starts and removes when it exits. scripts/run_marker.sh owns
# the format and the rules, including the kill -9 and pid-reuse cases.
#
# History. The first version tested one literal pgrep name and missed Happy
# Scribe, the second source: on 2026-09-11 this loop finished at 04:17:37Z and
# happyscribe_loop merged 8 transcripts at 04:49:11Z that nothing graded. The
# second version parsed the process list, and on the same day it answered "no
# source running" at 07:49:51Z while happyscribe_loop ran until 08:24:33Z. That
# never reproduced, so no cause is known. Process text is a guess about who is
# running; a marker is a claim the source makes about itself.
#
# A third source belongs in FETCHERS and nowhere else, and it must call
# claim_run_marker. Guarded by scripts/test_run_marker.py and
# scripts/test_fetcher_detection.py.
. scripts/run_marker.sh
FETCHERS=("fetch_loop.sh" "happyscribe_loop.sh")

# 0 a source is running, 1 none is, 2 a marker is unreadable.
fetcher_running(){
  local f rc
  for f in "${FETCHERS[@]}"; do
    run_marker_alive "$f"; rc=$?
    [ "$rc" -eq 0 ] && return 0
    [ "$rc" -eq 2 ] && return 2
  done
  return 1
}

BLIND_JUDGES="${BLIND_JUDGES:-fable,astra,gemini}"
OPEN_PER_LEADER="${OPEN_PER_LEADER:-2}"
CYCLE_SLEEP="${CYCLE_SLEEP:-300}"
FABLE_ACCOUNTS="${FABLE_ACCOUNTS:-}"  # pin Fable to named accounts, e.g. "default"
MIN_TO_START="${MIN_TO_START:-4}"      # do not spin up the expensive stage for 1 file
IDLE_EXIT="${IDLE_EXIT:-3}"            # consecutive no-op cycles with fetch gone -> stop

# Publish to verbatim-index.tonygwu.com ONCE, at the COMPLETE exit. Off unless
# set to 1, because a loop that can push to a public site is a different thing
# from a loop that writes files.
#
# WHY IT EXISTS. This loop rebuilds site/index.html every cycle and has never
# published it, so the live page only moves when a person runs deploy.sh. On
# 2026-09-09 that left a 13-hour stale board, and it recurred three more times
# in the two days after. The loop already knows the one moment when publishing
# is right: it has finished grading, and it rebuilt the board successfully.
#
# ONCE, and only at the exit, on purpose. Publishing every cycle would push a
# Cloudflare version every few minutes, nearly all of them transient states
# halfway through a grading pass.
#
# Reaching this point already proves the board is not stale: render_fail > 0
# exits 1 above, before the COMPLETE line.
PUBLISH_ON_COMPLETE="${PUBLISH_ON_COMPLETE:-0}"

stamp(){ date -u +%Y-%m-%dT%H:%M:%SZ; }
say(){ printf '[%s] %s\n' "$(stamp)" "$*"; }
count_tx(){ find data/transcripts -name '*.json' ! -name '*.tmp' 2>/dev/null | wc -l | tr -d ' '; }
count_grades(){ find data/grades -name '*.json' ! -name '*.tmp' -not -path '*/_raw/*' 2>/dev/null | wc -l | tr -d ' '; }

idle=0
cycle=0
render_fail=0   # consecutive cycles whose leaderboard rebuild did not complete
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
  #
  #    A render failure used to be SILENT. The two commands were chained with
  #    &&, so a failure just skipped the "re-rendered" line and the cycle
  #    carried on. A stale board and a fresh one read identically in this log.
  #    On 2026-09-09 aggregate.py died with a KeyError on every cycle for 13
  #    hours: the site kept serving the 01:40Z build, 96 new grades never
  #    reached it, and the loop still exited saying COMPLETE. Only
  #    grade_loop.err knew, and nothing reads that until something looks wrong.
  #
  #    Each stage now names its own failure, the run of failures is counted,
  #    and the loop refuses to call itself complete over a board it could not
  #    rebuild.
  if ! $PY scripts/aggregate.py --grades data/grades --roster data/roster/final.json \
        --transcripts data/transcripts_blind --out data/results.json \
        > /dev/null 2>>data/logs/grade_loop.err; then
    render_fail=$((render_fail + 1))
    say "  AGGREGATE FAILED (${render_fail} cycle(s) in a row). data/results.json and"
    say "    site/index.html both still hold the last build that succeeded."
    say "    last line of data/logs/grade_loop.err: $(tail -n 1 data/logs/grade_loop.err)"
  elif ! $PY scripts/build_site.py --results data/results.json --audit data/results_audit.json \
        --roster data/roster/final.json --calibration data/logs/calibration.json \
        --sources data/sources/discovered.json --out site/index.html \
        >> data/logs/grade_loop.out 2>>data/logs/grade_loop.err; then
    render_fail=$((render_fail + 1))
    say "  BUILD_SITE FAILED (${render_fail} cycle(s) in a row). data/results.json is current,"
    say "    site/index.html is NOT, so the two now disagree."
    say "    last line of data/logs/grade_loop.err: $(tail -n 1 data/logs/grade_loop.err)"
  else
    if [ "$render_fail" -gt 0 ]; then
      say "  render RECOVERED after ${render_fail} failed cycle(s)"
    fi
    render_fail=0
    say "  leaderboard re-rendered from $(count_grades) grades"
  fi

  g1=$(count_grades)
  gained=$(( g1 - g0 ))
  say "cycle ${cycle} done: +${gained} grades (total ${g1})"

  # Stop only when nothing is arriving AND every source has finished for good.
  if [ "$gained" -eq 0 ]; then
    fetcher_running; source_rc=$?
    if [ "$source_rc" -eq 2 ]; then
      # Waiting forever and exiting early are both guesses. Stop and say which file.
      say "  STOPPING: a run marker under ${RUN_MARKER_DIR} is unreadable (details above), so whether a transcript source is still running cannot be known. Inspect it, then restart."
      exit 1
    elif [ "$source_rc" -eq 0 ]; then
      say "  no new grades, but a transcript source is still running. waiting."
      idle=0
    else
      idle=$((idle + 1))
      say "  no new grades and no fetcher (${idle}/${IDLE_EXIT})"
      if [ "$idle" -ge "$IDLE_EXIT" ]; then
        # Grading being finished is not the same as the board being current.
        # Exiting 0 with "leaderboard at site/index.html" over a build that
        # failed 58 times is what let 2026-09-09 go unnoticed for 13 hours.
        if [ "$render_fail" -gt 0 ]; then
          say "STOPPING ON A STALE LEADERBOARD: nothing left to grade, but the rebuild has"
          say "  failed ${render_fail} cycle(s) in a row. site/index.html is the last build that"
          say "  succeeded, NOT these ${g1} grades. Fix the render, then re-run:"
          say "  bash scripts/deploy.sh --refresh"
          say "  see data/logs/grade_loop.err"
          exit 1
        fi
        if [ "$PUBLISH_ON_COMPLETE" = "1" ]; then
          # Plain deploy.sh, NOT --refresh. This cycle already aggregated and
          # rendered, so results.json is current; --refresh would re-aggregate
          # and also carries the daemon-clone precondition, which this does not
          # need. deploy.sh stays read-only on data/.
          say "  PUBLISH_ON_COMPLETE=1: publishing ${g1} grades to the live site"
          if bash scripts/deploy.sh >> data/logs/grade_loop.out 2>>data/logs/grade_loop.err; then
            say "  published. live site now matches this build"
          else
            # Grading succeeded and the board on disk is good; only the push
            # failed. Say which, and exit non-zero so it is not mistaken for a
            # clean finish. Silence here would recreate the bug this replaces.
            say "PUBLISH FAILED: grading finished and site/index.html is current on disk,"
            say "  but the deploy did not complete, so the LIVE site is unchanged."
            say "  last line of data/logs/grade_loop.err: $(tail -n 1 data/logs/grade_loop.err)"
            say "  retry by hand: bash scripts/deploy.sh"
            exit 1
          fi
        fi
        say "COMPLETE: nothing left to grade. leaderboard at site/index.html"
        exit 0
      fi
    fi
  else
    idle=0
  fi
  sleep "$CYCLE_SLEEP"
done
