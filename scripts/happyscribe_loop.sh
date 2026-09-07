#!/usr/bin/env bash
# Happy Scribe fetching daemon, run alongside fetch_loop.sh.
#
# Safe to run at the same time as the YouTube loop. They touch different hosts,
# so neither one's rate limit affects the other, and that is the whole point:
# when YouTube blocks this IP, this path keeps supplying transcripts.
#
# Every cycle: fetch what is missing, then dedupe against the existing corpus
# and merge only what is genuinely new. The dedupe step is not optional. Both
# sources carry the same popular episodes, and grading one appearance twice
# would let it move a leader's average twice as much as anyone else's.
#
#   nohup bash scripts/happyscribe_loop.sh > data/logs/happyscribe_loop.log 2>&1 &
set -uo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
TARGET="${TARGET:-5}"
INTERVAL="${INTERVAL:-1.5}"      # seconds between requests to happyscribe
WORKERS="${WORKERS:-3}"
CYCLE_SLEEP="${CYCLE_SLEEP:-1800}"
CANDS=data/sources/happyscribe_candidates.json

stamp(){ date -u +%Y-%m-%dT%H:%M:%SZ; }
say(){ printf '[%s] %s\n' "$(stamp)" "$*"; }

# Discovery walks 38 sitemaps, so it is done once and reused. Delete the
# candidates file to force a refresh when new episodes are worth picking up.
if [ ! -s "$CANDS" ]; then
  say "no candidate file; running discovery"
  $PY scripts/fetch_happyscribe.py --discover --roster data/roster/final.json \
      --candidates "$CANDS" --interval "$INTERVAL" >/dev/null 2>>data/logs/happyscribe_loop.err
fi

cycle=0
while true; do
  cycle=$((cycle + 1))
  say "cycle ${cycle}: fetching"
  $PY scripts/fetch_happyscribe.py --fetch --candidates "$CANDS" \
      --out data/transcripts_hs --target-per-leader "$TARGET" \
      --interval "$INTERVAL" --workers "$WORKERS" \
      >>data/logs/happyscribe_loop.out 2>>data/logs/happyscribe_loop.err

  # Merge only non-duplicates, then sweep the whole corpus for same-source
  # re-uploads that the cross-source pass cannot see.
  before=$(find data/transcripts -name '*.json' ! -name '*.tmp' ! -name '*.superseded' | wc -l | tr -d ' ')
  $PY scripts/dedupe_transcripts.py --merge >/dev/null 2>>data/logs/happyscribe_loop.err
  $PY scripts/dedupe_transcripts.py --sweep >>data/logs/dedupe_sweep.log 2>>data/logs/happyscribe_loop.err
  after=$(find data/transcripts -name '*.json' ! -name '*.tmp' ! -name '*.superseded' | wc -l | tr -d ' ')
  say "cycle ${cycle}: corpus ${before} -> ${after}"

  hs=$(find data/transcripts_hs -name '*.json' ! -name '*.tmp' 2>/dev/null | wc -l | tr -d ' ')
  cand=$($PY -c "import json;d=json.load(open('$CANDS'));print(sum(len(v) for v in d.values()))" 2>/dev/null || echo 0)
  if [ "${hs:-0}" -ge "${cand:-0}" ]; then
    say "COMPLETE: every discovered candidate has been fetched (${hs}/${cand})"
    exit 0
  fi
  sleep "$CYCLE_SLEEP"
done
