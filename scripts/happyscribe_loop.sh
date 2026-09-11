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

# Every clone shares one data/ checkout, so a loop started in the wrong clone
# writes the live corpus rather than a private copy.
. scripts/daemon_guard.sh
require_daemon_clone || exit 1

PY=.venv/bin/python
TARGET="${TARGET:-5}"
INTERVAL="${INTERVAL:-1.5}"      # seconds between requests to happyscribe
WORKERS="${WORKERS:-3}"
CYCLE_SLEEP="${CYCLE_SLEEP:-1800}"
CANDS=data/sources/happyscribe_candidates.json

stamp(){ date -u +%Y-%m-%dT%H:%M:%SZ; }
say(){ printf '[%s] %s\n' "$(stamp)" "$*"; }

# Discovery walks 38 sitemaps, so it is not repeated for its own sake. It IS
# repeated when the roster gains a leader the pool has never been searched for,
# because the pool is derived from the roster and has to track it.
#
# This used to read `if [ ! -s "$CANDS" ]`, so the pool was built once and the
# roster could move underneath it forever. It did: the roster grew from 40 to 50
# on 2026-09-10 and eleven leaders were never searched, while C.C. Wei stayed in
# the pool after leaving the study. This loop reported COMPLETE throughout,
# truthfully, because every candidate it knew of had been fetched. It knew of
# none for those eleven, and no log line said so. The operator found it by asking.
#
# A leader present with an EMPTY list counts as searched. Larry Ellison, Michael
# Dell and Sergey Brin were searched and genuinely have no podcast appearances,
# so treating empty as unsearched would re-walk all 38 sitemaps every cycle.
unsearched=$($PY scripts/fetch_happyscribe.py --report-unsearched \
    --roster data/roster/final.json --candidates "$CANDS" \
    2>>data/logs/happyscribe_loop.err)
if [ ! -s "$CANDS" ] || [ -n "$unsearched" ]; then
  if [ -n "$unsearched" ]; then
    say "roster has unsearched leaders, re-running discovery: ${unsearched}"
  else
    say "no candidate file; running discovery"
  fi
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
