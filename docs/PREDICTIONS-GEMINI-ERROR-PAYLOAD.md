# agy can return a COMPLETE verdict with status ERROR, and the harness throws it away

Found 2026-09-16 by repo-1, confirmed here with the raw response. Not fixed;
the fix belongs to whoever owns `grade.py`, and the reasoning is below.

## What happens

`call_gemini` in `scripts/grade.py` rejects on the wrapper status before it ever
looks at the payload:

```python
if result.get("status") != "SUCCESS":
    blob = json.dumps(result)
    kind, detail = classify_agy_failure(proc.returncode, blob)
    ...
    raise RuntimeError(detail)

text = result.get("response") or ""      # never reached
```

So a turn that agy marks `ERROR` is discarded unread, whatever it contains, and
the taxonomy files it as `cli_nonzero_exit` with `rc=0`. Exit code zero with a
non-empty body is not the documented empty-response bug, which is the signal
repo-1 spotted in the log.

## The evidence

Run `20260916T040112Z-verify-450b7964`, Gemini re-verification of repo-1's
supplemental corpus: 89 attempted, 13 failed, all `cli_nonzero_exit`, 13 distinct
transcripts with one failure each.

Twelve of the thirteen raw responses were overwritten by the retry pass that
recovered them. One survived, `thomas-kurian/web-stratechery-com-4ba38abb`:

```
7,378 bytes
top-level keys: schema_version, transcript_id, verdicts
verdicts: 12, every one with prediction_id, gates, attribution,
          claim_faithful, resolution_criteria, notes, qualifies
validates against verifier_output.schema.json: YES
```

**Twelve complete, schema-valid verdicts, paid for and discarded.** The count is
the tell that it was not truncated: `VERIFY_BATCH` is 12, so this is exactly one
full batch rather than a payload that stopped early.

## Blast radius: the predictions verify path, not the leaders board

MEASURED over the leaders error logs:

```
grade_errors_open.jsonl     0 of 266 cli_nonzero_exit carry rc=0
grade_errors_blind.jsonl    0 of 0
grade_errors_gemini.jsonl   0 of 0
```

So this shape has never been observed in leaders grading. It appeared here on the
verification prompt, which asks for a large structured JSON object rather than a
grade. That is a difference worth keeping in mind before generalising: the
published leaderboard has not silently lost grades this way.

## Why it is not fixed here

The obvious fix is to read the payload when the status is not SUCCESS, accept it
if it parses and validates, and record that it came from an ERROR turn. That is
exactly the "be liberal in what you accept" branch CLAUDE.md forbids, and the
counter-argument is real: nobody knows WHY agy said ERROR, and a payload that
validates can still be wrong in a way the schema cannot see.

The argument the other way is that the taxonomy currently lies. A call that
produced twelve schema-valid verdicts is reported as a CLI crash, which sends the
next reader looking for a harness fault that is not there, and costs a paid
re-call every time.

A middle option, if repo-0 wants one: keep raising, but attach the payload to the
error so the waste is visible and a later pass can recover it without a new call.
That changes no verdict and removes the lie.

**Practical cost here was small**, because agy failures are not deterministic:
re-running recovered 12 of the 13, and the corpus finished at 216 of 216
Gemini-verified. The cost is the 13 wasted calls and the misleading label.

## How to re-derive

```
# the surviving raw response
find data/predictions/_experiments/phase2-scoring-20260915/corpus-supplemental-gemini/_raw \
     -name '*stratechery-com-4ba38abb*450b7964*'

# validate it
.venv/bin/python - <<'EOF'
import json, pathlib, sys
sys.path.insert(0, "scripts")
import predictions_lib as L
o = json.loads(pathlib.Path(PATH).read_text())
schema = json.loads(pathlib.Path(
    ".claude/skills/prediction-extractor/verifier_output.schema.json").read_text())
print(len(o["verdicts"]), "verdicts;", L.check_schema(o, schema) or "schema OK")
EOF
```
