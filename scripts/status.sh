#!/usr/bin/env bash
# One screen showing where each independent stage stands, and what to run next.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python

b(){ printf '\n\033[1m%s\033[0m\n' "$*"; }

BRIEF=0
[ "${1:-}" = "--brief" ] && BRIEF=1

# The flag file lags reality. It is only written after a failed probe at the
# TOP of a cycle, so while the loop is mid-pass the flag can read clear for
# minutes after YouTube has actually blocked us. Observed exactly that: probe
# said IpBlocked while status.sh showed no banner. So probe live here. It costs
# one caption request, and when blocked it fails in about a second.
YT_STATE=$($PY - <<'PYEOF' 2>/dev/null
from youtube_transcript_api import YouTubeTranscriptApi
try:
    l = YouTubeTranscriptApi().list("93piVCwqXz8")
    try: t = l.find_manually_created_transcript(["en","en-US","en-GB"])
    except Exception: t = l.find_generated_transcript(["en","en-US","en-GB"])
    t.fetch(); print("CLEAR")
except Exception as e: print(type(e).__name__)
PYEOF
)
if [ "$YT_STATE" != "CLEAR" ]; then
  printf '\n\033[1;31m  >>> ROTATE THE VPN — youtube is %s right now <<<\033[0m\n' "$YT_STATE"
  printf '  (live probe, not the flag file. The loop resumes on its own within 60s of a new IP.)\n'
else
  printf '\n\033[1;32m  youtube: CLEAR\033[0m  (live probe)\n'
fi

if [ -f data/logs/NEEDS_IP_ROTATION ]; then
  printf '  (loop also has a stale rotation flag from: '
  printf '  %s\n' "$(cat data/logs/NEEDS_IP_ROTATION)"
  printf '  The fetch loop re-probes every 60s and resumes on its own once the IP changes.\n'
fi

b "PROCESSES"
# Three independent daemons, not one. happyscribe_loop was missing entirely,
# and "grading" checked for the grade.py SUBPROCESS rather than the daemon, so
# it read "stopped" in the gaps between judge calls while the loop was alive.
for L in fetch_loop happyscribe_loop grade_loop; do
  case "$L" in
    fetch_loop)       desc="youtube captions (needs VPN)" ;;
    happyscribe_loop) desc="happyscribe (no VPN needed)" ;;
    grade_loop)       desc="grading + render" ;;
  esac
  if pgrep -f "$L.sh" >/dev/null; then
    printf "  %-18s RUNNING  pid %-7s %s\n" "$L" "$(pgrep -f "$L.sh" | head -1)" "$desc"
  else
    printf "  %-18s stopped           %s\n" "$L" "$desc"
  fi
done
inflight=$(pgrep -f "scripts/grade.py" | wc -l | tr -d ' ')
printf "  %-18s %s judge call(s) in flight right now\n" "" "$inflight"

b "FETCH"
$PY - <<'PYEOF'
import json
from collections import Counter
from pathlib import Path
roster = [r["slug"] for r in json.loads(Path("data/roster/final.json").read_text())["roster"]]
counts = {s: len(list((Path("data/transcripts") / s).glob("*.json"))) for s in roster}
total = sum(counts.values())
words = 0
for p in Path("data/transcripts").rglob("*.json"):
    try: words += json.loads(p.read_text()).get("word_count", 0)
    except Exception: pass
dist = Counter(counts.values())
print(f"  transcripts        {total}  ({words/1000:.0f}k words)")
print(f"  leaders at 5+      {sum(1 for v in counts.values() if v >= 5)}/{len(roster)}")
print(f"  leaders at 3+      {sum(1 for v in counts.values() if v >= 3)}/{len(roster)}")
print(f"  leaders at zero    {sum(1 for v in counts.values() if v == 0)}")
print(f"  per-leader spread  " + ", ".join(f"{k}:{v}" for k, v in sorted(dist.items())))
zero = [s for s, v in counts.items() if v == 0]
if zero:
    print(f"  still empty        {', '.join(zero[:8])}{' ...' if len(zero) > 8 else ''}")
PYEOF

# Error taxonomy across every cycle, so a broken component reads as broken
# rather than as slow.
if ls data/logs/fetch_errors_cycle*.jsonl >/dev/null 2>&1; then
  printf "  recent errors      "
  cat data/logs/fetch_errors_cycle*.jsonl 2>/dev/null \
    | $PY -c "
import sys, json
from collections import Counter
c = Counter()
for line in sys.stdin:
    try: c[json.loads(line).get('error_type','?')] += 1
    except Exception: pass
print(', '.join(f'{k}={v}' for k, v in c.most_common()) or 'none')"
fi

b "GRADING"
$PY - <<'PYEOF'
import json
from collections import Counter
from pathlib import Path
root = Path("data/grades")
if not root.exists():
    print("  no grades yet")
else:
    rows = []
    for p in root.rglob("*.json"):
        if "_raw" in p.parts: continue
        try: rows.append(json.loads(p.read_text()))
        except Exception: pass
    if not rows:
        print("  no grades yet")
    else:
        c = Counter((r["judge"], r["mode"]) for r in rows)
        bad = sum(1 for r in rows if r.get("validation_errors"))
        print(f"  grades on disk     {len(rows)}  ({bad} failed validation)")
        # Import the shadow list rather than repeating or regex-parsing it. A
        # second copy drifts, and the copy that drifts is the one that tells the
        # operator an arm is published when it is not. Regex-parsing was that
        # same bug wearing a disguise: it would silently return an empty set the
        # day the declaration is reformatted onto two lines.
        import sys as _sys
        _sys.path.insert(0, "scripts")
        try:
            from aggregate import SHADOW_JUDGES as _sj
            shadow = set(_sj)
        except Exception as _e:
            print(f"  WARNING: cannot read SHADOW_JUDGES ({_e}); "
                  f"shadow arms will not be marked")
            shadow = set()
        for (j, m), n in sorted(c.items()):
            tag = "  [shadow: collected, NOT published]" if j in shadow else ""
            print(f"    {j:6} {m:8}   {n}{tag}")
PYEOF

b "ANTIGRAVITY (gemini judge)"
$PY - <<'PYEOF'
import json, re
from pathlib import Path

# Profiles are a glob, never a hardcoded list of accounts: this machine has
# already been bitten twice by hardcoded Claude account letters.
homes = [Path.home()]
root = Path.home() / ".agy-homes"
if root.is_dir():
    homes += sorted(d for d in root.iterdir()
                    if (d / ".gemini" / "antigravity-cli").is_dir())

def identity(home):
    """Newest log BY FILENAME, never by mtime. A renamed or reused profile keeps
    its old logs, and mtime says when a file was touched, not what is in it.
    Sorting by mtime named the wrong account here on 2026-09-07."""
    d = home / ".gemini" / "antigravity-cli" / "log"
    for f in sorted(d.glob("*.log"), reverse=True)[:25] if d.is_dir() else []:
        hits = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                          f.read_text(errors="ignore"))
        if hits:
            return hits[-1]
    return "unknown"

for h in homes:
    label = "default" if h == Path.home() else h.name
    print(f"  profile {label:<14} {identity(h)}")
if len(homes) < 2:
    print("  only one profile: the rotation has nothing to rotate over")
print("  quota             not measurable; agy exposes no usage endpoint, so the")
print("                    rotation is round-robin and a stop shows as auth_or_quota")

# Backfill progress. An uneven judge mix is what calibration cannot fix, so the
# arm may only be promoted once this reaches the full corpus.
corpus = {(p.parent.name, p.stem) for p in Path("data/transcripts_blind").rglob("*.json")}
graded = set()
gd = Path("data/grades/gemini")
if gd.is_dir():
    for p in gd.rglob("*.json"):
        if "_raw" in p.parts: continue
        try: r = json.loads(p.read_text())
        except Exception: continue
        if r.get("mode") == "blinded":
            graded.add((r["leader_slug"], r["source_id"]))
n, tot = len(graded), len(corpus)
pct = (100.0 * n / tot) if tot else 0.0
bar = "#" * int(pct // 5) + "." * (20 - int(pct // 5))
print(f"  backfill          [{bar}] {n}/{tot} blinded transcripts ({pct:.1f}%)")
if tot and n < tot:
    print(f"                    {tot - n} to go before the arm can leave shadow mode")
PYEOF

if [ "$BRIEF" -eq 0 ]; then
  b "PER-LEADER COVERAGE"
  # Do not swallow stderr here. It used to be 2>/dev/null, which turned any
  # crash in coverage_table.py into an empty section that reads as "no data".
  if cov=$($PY scripts/coverage_table.py 2>&1); then
    printf '%s\n' "$cov" | sed 's/^/  /'
  else
    printf '  \033[1;31mcoverage_table.py FAILED\033[0m\n'
    printf '%s\n' "$cov" | tail -5 | sed 's/^/    /'
  fi
fi

b "NEXT"
n=$(find data/transcripts -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
if [ "${n:-0}" -lt 40 ]; then
  echo "  wait for the fetch loop. start it if stopped:"
  echo "    nohup bash scripts/fetch_loop.sh > data/logs/fetch_loop.log 2>&1 &"
else
  echo "  enough transcripts to grade. these are independent of fetching:"
  echo "    STAGES=\"3 4\" bash scripts/run_pipeline.sh          # qa + blind"
  echo "    STAGES=\"5\"   WORKERS=10 bash scripts/run_pipeline.sh # blinded grading"
  echo "    STAGES=\"6\"   WORKERS=10 bash scripts/run_pipeline.sh # unblinded, halo only"
  echo "    STAGES=\"7 8\" bash scripts/run_pipeline.sh          # aggregate + render"
fi
echo
