"""JSONL is split on "\\n", never by str.splitlines().

JSON permits VT, FF, FS, GS, RS, NEL, U+2028 and U+2029 RAW inside a string.
`str.splitlines()` breaks on every one of them, so a record carrying one was cut
in half and the half failed as `Unterminated string starting at column 5435`.
The message named a column, which is why the cause took a while to find; the
character responsible was 555 characters further on.

FOUND on a Stripe annual-letter PDF whose image caption carried one U+2028. The
file was 9564 bytes, 9522 characters, and held exactly one "\\n" byte, and
`splitlines()` returned two lines. The existing YouTube corpus carries none of
these code points, so this was latent until a PDF entered the pipeline.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import predictions_lib as L  # noqa: E402

CHECKS = 0
FAILED: list[str] = []


def check(label: str, got, want) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILED.append(f"{label}\n     got:  {got!r}\n     want: {want!r}")


# The old behaviour, so the comparison is BEHAVIOURAL rather than an
# AttributeError when this file is run against a predictions_lib without the fix.
split_lines = getattr(L, "jsonl_lines", lambda t: t.splitlines())

# Code points str.splitlines() breaks on that "\n".split does not. json.dumps
# ALWAYS escapes the C0 controls (VT, FF, FS, GS, RS), because JSON requires it,
# so those cannot reach a file raw. Only these three can, and only under
# ensure_ascii=False, which is exactly how this repo serialises records.
RAW_CAPABLE = {"NEL": "\x85", "LINE SEP": " ", "PARA SEP": " "}

for name, ch in RAW_CAPABLE.items():
    payload = json.dumps({"quote": f"before{ch}after", "n": 1}, ensure_ascii=False) + "\n"
    # The hazard is real: confirm splitlines() really would have broken it.
    check(f"{name}: splitlines would split the record", len(payload.splitlines()), 2)
    check(f"{name}: we keep one record", len(split_lines(payload)), 1)
    recs = L.parse_lines(payload, "t")
    check(f"{name}: record parses", len(recs), 1)
    check(f"{name}: the character survives verbatim", recs[0]["quote"], f"before{ch}after")

# The C0 controls cannot appear raw, but the splitter must be safe if one does.
for name, ch in {"VT": "\x0b", "FF": "\x0c", "FS": "\x1c",
                 "GS": "\x1d", "RS": "\x1e"}.items():
    check(f"{name}: json escapes it, so one line either way",
          len((json.dumps({"q": f"a{ch}b"}, ensure_ascii=False) + "\n").splitlines()), 1)
    check(f"{name}: a raw one would not split us", len(split_lines(f'{{"q":"a{ch}b"}}\n')), 1)

# --- ordinary behaviour is unchanged ----------------------------------------

two = json.dumps({"a": 1}) + "\n" + json.dumps({"a": 2}) + "\n"
check("two records parse", len(L.parse_lines(two, "t")), 2)
check("no trailing empty record", len(split_lines(two)), 2)
check("missing final newline still parses", len(L.parse_lines(json.dumps({"a": 1}), "t")), 1)
check("empty payload is no records", split_lines(""), [])
# A lone newline yields one EMPTY line, exactly as splitlines() did, and
# parse_lines still rejects it as a blank line. Behaviour deliberately unchanged.
check("a lone newline is one blank line", split_lines("\n"), [""])

# CRLF: the \r stays on the line and json tolerates trailing whitespace.
crlf = json.dumps({"a": 1}) + "\r\n" + json.dumps({"a": 2}) + "\r\n"
check("crlf payload parses", [r["a"] for r in L.parse_lines(crlf, "t")], [1, 2])

# A blank line is still an error, and still names its line number.
try:
    L.parse_lines(json.dumps({"a": 1}) + "\n\n" + json.dumps({"a": 2}) + "\n", "f")
    check("blank line raises", "no raise", "raise")
except L.PredictionError as exc:
    check("blank line still raises on line 2", "f:2:" in str(exc), True)

# Malformed JSON still raises with its line number.
try:
    L.parse_lines('{"a": 1}\n{not json}\n', "f")
    check("bad json raises", "no raise", "raise")
except L.PredictionError as exc:
    check("bad json names line 2", "f:2:" in str(exc), True)

# --- the real record shape that failed --------------------------------------

record = {"prediction_id": "abc", "source": {
    "quote_original": "We expect to be profitable in 2025 and beyond.",
    "context_before": "Steampunk payment cards, courtesy of Midjourney v5",
}}
payload = json.dumps(record, ensure_ascii=False) + "\n"
check("the real shape is one line to us", len(split_lines(payload)), 1)
check("the real shape is two to splitlines", len(payload.splitlines()), 2)
got = L.parse_lines(payload, "t")[0]
check("context survives", got["source"]["context_before"],
      "Steampunk payment cards, courtesy of Midjourney v5")

# ensure_ascii=True escapes U+2028, so only unescaped writers are exposed.
check("ensure_ascii escapes it away",
      len((json.dumps(record) + "\n").splitlines()), 1)

print(f"test_jsonl_line_splitting: {CHECKS} checks, {len(FAILED)} failed")
for f in FAILED:
    print("  FAIL " + f)
sys.exit(1 if FAILED else 0)
