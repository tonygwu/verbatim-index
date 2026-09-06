#!/usr/bin/env bash
# One screen showing where each independent stage stands, and what to run next.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python

b(){ printf '\n\033[1m%s\033[0m\n' "$*"; }

if [ -f data/logs/NEEDS_IP_ROTATION ]; then
  printf '\n\033[1;31m  >>> ACTION NEEDED: ROTATE THE VPN <<<\033[0m\n'
  printf '  %s\n' "$(cat data/logs/NEEDS_IP_ROTATION)"
  printf '  The fetch loop re-probes every 60s and resumes on its own once the IP changes.\n'
fi

b "PROCESSES"
if pgrep -f "fetch_loop.sh" >/dev/null; then
  printf "  fetch loop   RUNNING  pid %s\n" "$(pgrep -f fetch_loop.sh | head -1)"
else
  printf "  fetch loop   stopped\n"
fi
if pgrep -f "scripts/grade.py" >/dev/null; then
  printf "  grading      RUNNING  pid %s\n" "$(pgrep -f 'scripts/grade.py' | head -1)"
else
  printf "  grading      stopped\n"
fi

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
        for (j, m), n in sorted(c.items()):
            print(f"    {j:6} {m:8}   {n}")
PYEOF

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
