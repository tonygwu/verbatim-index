#!/usr/bin/env bash
# End-to-end pipeline: discovered sources -> transcripts -> grades -> leaderboard.
#
# Every stage is resumable. Re-running skips work already on disk unless FORCE=1.
# Stages 5 and 6 are the expensive ones: each judge call takes roughly ten
# minutes, so the full grading run is measured in hours, not minutes.
#
# Usage:
#   scripts/run_pipeline.sh            # all stages
#   STAGES="1 2 3 4" scripts/run_pipeline.sh   # prepare transcripts only
#   STAGES="7 8" scripts/run_pipeline.sh       # re-aggregate and re-render
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
STAGES="${STAGES:-1 2 3 4 5 6 7 8}"
WORKERS="${WORKERS:-12}"
OPEN_PER_LEADER="${OPEN_PER_LEADER:-2}"
FORCE_FLAG=""
[ "${FORCE:-0}" = "1" ] && FORCE_FLAG="--force"

has(){ [[ " $STAGES " == *" $1 "* ]]; }
banner(){ printf '\n\033[1m=== stage %s: %s ===\033[0m\n' "$1" "$2"; }

has 1 && { banner 1 "discovered sources -> manifest, aliases, repairs"
  $PY scripts/sources_to_manifest.py \
    --sources data/sources/discovered.json \
    --manifest data/sources/all.jsonl \
    --aliases  data/sources/aliases.json \
    --repairs  data/sources/repairs.json
}

has 2 && { banner 2 "fetch verbatim captions"
  $PY scripts/fetch_transcripts.py \
    --manifest data/sources/all.jsonl \
    --out      data/transcripts \
    --errors   data/logs/fetch_errors.jsonl \
    --workers 6 $FORCE_FLAG
}

has 3 && { banner 3 "quality-gate the transcripts"
  $PY scripts/qa_transcripts.py \
    --transcripts data/transcripts \
    --roster      data/roster/final.json \
    --glossaries  data/sources/aliases.json \
    --out         data/logs/transcript_qa.json
}

has 4 && { banner 4 "repair speech-recognition errors, then blind and un-blind"
  $PY scripts/normalize_transcripts.py --mode blinded \
    --transcripts data/transcripts --out data/transcripts_blind \
    --roster data/roster/final.json --repairs data/sources/repairs.json \
    --aliases data/sources/aliases.json --qa data/logs/transcript_qa.json \
    --log data/logs/normalize_blind.json
  $PY scripts/normalize_transcripts.py --mode open \
    --transcripts data/transcripts --out data/transcripts_open \
    --roster data/roster/final.json --repairs data/sources/repairs.json \
    --aliases data/sources/aliases.json --qa data/logs/transcript_qa.json \
    --log data/logs/normalize_open.json
  $PY scripts/test_blinding.py
}

has 5 && { banner 5 "BLINDED grading, both judges, every transcript (the published score)"
  $PY scripts/grade.py \
    --transcripts data/transcripts_blind --roster data/roster/final.json \
    --out data/grades --judges fable,astra --modes blinded --repeats 1 \
    --workers "$WORKERS" --errors data/logs/grade_errors_blind.jsonl \
    --timeout 2400 $FORCE_FLAG
}

has 6 && { banner 6 "UNBLINDED grading on $OPEN_PER_LEADER transcripts per leader (halo measurement only)"
  $PY scripts/grade.py \
    --transcripts data/transcripts_open --roster data/roster/final.json \
    --out data/grades --judges fable,astra --modes open --repeats 1 \
    --limit-per-leader "$OPEN_PER_LEADER" \
    --workers "$WORKERS" --errors data/logs/grade_errors_open.jsonl \
    --timeout 2400 $FORCE_FLAG
}

has 7 && { banner 7 "aggregate to per-leader scores"
  $PY scripts/aggregate.py \
    --grades data/grades --roster data/roster/final.json \
    --transcripts data/transcripts_blind --out data/results.json
}

has 8 && { banner 8 "render the leaderboard"
  $PY scripts/build_site.py \
    --results data/results.json --audit data/results_audit.json \
    --roster data/roster/final.json --calibration data/logs/calibration.json \
    --sources data/sources/discovered.json --out site/index.html
}

printf '\n\033[1mdone.\033[0m  leaderboard: site/index.html\n'
