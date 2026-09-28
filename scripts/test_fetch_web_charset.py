#!/usr/bin/env python3
"""A page served without a charset in its Content-Type must not become mojibake.

FOUND 2026-09-27 on round 3 of the supplemental sweep. `extract()` read
`resp.text`, and requests decodes a `text/html` body that carries no charset in
the HTTP header as ISO-8859-1, which is the old HTTP/1.1 default. palantir.com,
deepmind.google, threadreaderapp.com and others send UTF-8 with the charset
declared only in `<meta charset="utf-8">`, so every curly apostrophe became the
three characters "â\\x80\\x99". 13 of 94 round-3 transcripts carried it, and 17
of 270 in production `transcripts_web`. A model quoting "We’ve" cannot ground
against "Weâ\\x80\\x99ve", so the damage is silent: the source reads as low-yield.

The rule now: the HTTP header's charset, else the page's own <meta> charset,
else UTF-8 if and only if the bytes are valid UTF-8, else REFUSE. Decoding is
strict, never "replace", because a replacement character is a quiet change of
text. The record names the charset and where it came from.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fetch_web_sources as F  # noqa: E402

checks = 0
failures: list[str] = []


def check(label: str, got, want) -> None:
    global checks
    checks += 1
    if got != want:
        failures.append(f"{label}\n     got  {got!r}\n     want {want!r}")


class Resp:
    """Mimics requests: `.text` decodes as ISO-8859-1 when the header has no charset."""

    def __init__(self, body: bytes, ctype: str) -> None:
        self.status_code = 200
        self.content = body
        self.headers = {"content-type": ctype}
        enc = "iso-8859-1"
        if "charset=" in ctype:
            enc = ctype.split("charset=")[1].split(";")[0].strip()
        self.text = body.decode(enc, errors="replace")


WORDS = " ".join(f"word{i}" for i in range(500))
SENT = "We’ve said we’ll be profitable by the end of 2024 — and we will."


def page(meta: str = "") -> bytes:
    return (f"<html><head>{meta}<title>t</title></head><body><article><p>{SENT}</p>"
            f"<p>{WORDS}</p></article></body></html>").encode("utf-8")


def text_of(resp):
    try:
        return F.extract(resp)[0]
    except Exception as exc:  # noqa: BLE001
        return f"RAISED {type(exc).__name__}: {exc}"


# 1. meta charset only: the case that produced the mojibake
check("meta charset, no header charset: sentence survives intact",
      SENT in text_of(Resp(page('<meta charset="utf-8">'), "text/html")), True)
check("meta charset: no mojibake", "â" in text_of(Resp(page('<meta charset="utf-8">'), "text/html")), False)

# 2. http-equiv form of the meta declaration
check("http-equiv meta charset",
      SENT in text_of(Resp(page('<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">'),
                           "text/html")), True)

# 3. no declaration anywhere, but valid UTF-8 bytes
check("undeclared but valid UTF-8", SENT in text_of(Resp(page(), "text/html")), True)

# 4. header charset still wins, and still works
check("header charset", SENT in text_of(Resp(page(), "text/html; charset=utf-8")), True)

# 5. undeclared AND not valid UTF-8: refuse, do not guess
latin = page().replace("’".encode("utf-8"), b"\x92")  # a cp1252 apostrophe, invalid UTF-8
got = text_of(Resp(latin, "text/html"))
check("undeclared, invalid UTF-8 is refused as not verbatim",
      got.startswith("RAISED NotVerbatim"), True)

# 6. a header that lies (says utf-8, bytes are not) is refused, not replaced
got = text_of(Resp(latin, "text/html; charset=utf-8"))
check("declared utf-8 with invalid bytes is refused rather than replaced",
      got.startswith("RAISED NotVerbatim"), True)

# 7. the record says which charset was used and why
try:
    text, how = F.extract(Resp(page('<meta charset="utf-8">'), "text/html"))
    check("how names the charset basis", "charset=utf-8/meta_charset" in how, True)
except Exception as exc:  # noqa: BLE001
    checks += 1
    failures.append(f"extract raised on a good page: {exc}")

if failures:
    print(f"FAIL {len(failures)} of {checks} checks")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print(f"ok {checks} checks")
