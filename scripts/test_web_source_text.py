"""Checks for the verbatim HTML-to-text extractor.

The property that matters is not "the text looks clean". It is that a quote a
model proposes can be found by an EXACT span match in the output, because
ground_candidates() drops anything it cannot match and never repairs it. So
most of these cases assert `sentence in html_to_text(page)`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from web_source_text import (  # noqa: E402
    assert_verbatim, html_to_text, letter_stream, words,
)

CHECKS = 0
FAILED: list[str] = []


def check(label: str, got, want) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILED.append(f"{label}\n     got:  {got!r}\n     want: {want!r}")


def check_true(label: str, cond: bool) -> None:
    check(label, bool(cond), True)


def check_raises(label: str, fn, exc=Exception) -> None:
    global CHECKS
    CHECKS += 1
    try:
        fn()
    except exc:
        return
    except Exception as other:  # noqa: BLE001
        FAILED.append(f"{label}\n     raised {type(other).__name__}, wanted {exc.__name__}")
        return
    FAILED.append(f"{label}\n     did not raise {exc.__name__}")


# --- block structure ---------------------------------------------------------

check("paragraphs separate", html_to_text("<p>One.</p><p>Two.</p>"), "One.\n\nTwo.")
check("block tags do not join words", words(html_to_text("<p>foo</p><p>bar</p>")), ["foo", "bar"])
check("inline tags do not split a word", html_to_text("<p>Q<b>1</b> 2026</p>"), "Q1 2026")
check("br is a single newline", html_to_text("<p>a<br>b</p>"), "a\nb")
check("headings separate", html_to_text("<h2>Title</h2><p>Body.</p>"), "Title\n\nBody.")
check("list items separate", words(html_to_text("<ul><li>one</li><li>two</li></ul>")), ["one", "two"])
check("table cells separate", words(html_to_text("<tr><td>a</td><td>b</td></tr>")), ["a", "b"])
check("runs of blank lines collapse", html_to_text("<div><div><p>x</p></div></div>"), "x")

# --- dropped elements --------------------------------------------------------

check("script is dropped", html_to_text("<p>keep</p><script>var drop=1;</script>"), "keep")
check("style is dropped", html_to_text("<style>p{color:red}</style><p>keep</p>"), "keep")
check("nav is dropped", html_to_text("<nav><a>Home</a></nav><p>keep</p>"), "keep")
check("footer is dropped", html_to_text("<p>keep</p><footer>(c) 2026</footer>"), "keep")
check("nested drop closes once", html_to_text("<nav><div><span>x</span></div></nav><p>keep</p>"), "keep")
check("drop tag with attributes", html_to_text('<script type="text/javascript">x</script><p>keep</p>'), "keep")
check("comments are dropped", html_to_text("<p>keep</p><!-- <p>drop</p> -->"), "keep")

# --- verbatim text -----------------------------------------------------------

check("entities unescape", html_to_text("<p>AT&amp;T &quot;grows&quot;</p>"), 'AT&T "grows"')
check("numeric entity unescapes", html_to_text("<p>50&#37; by 2030</p>"), "50% by 2030")
check("nbsp becomes a space", html_to_text("<p>10&nbsp;billion</p>"), "10 billion")
check("zero width space removed", html_to_text("<p>AI​future</p>"), "AIfuture")
check("soft hyphen removed", html_to_text("<p>super­intelligence</p>"), "superintelligence")
check("em dash survives", html_to_text("<p>a — b</p>"), "a — b")
check("curly quotes survive", html_to_text("<p>“yes”</p>"), "“yes”")
check("accents compose to NFC", html_to_text("<p>Lütke</p>"), "Lütke")

# --- the property the pipeline depends on ------------------------------------

SENTENCE = "By 2027, we will have more than one million units in the field."
PAGE = (
    "<html><head><title>T</title><style>x{}</style></head><body>"
    "<nav><a href='/'>Home</a></nav>"
    "<article><p>Analyst: what is the outlook?</p>"
    f"<p><b>CEO:</b> {SENTENCE} That is our plan.</p></article>"
    "<footer>copyright</footer></body></html>"
)
OUT = html_to_text(PAGE)
check_true("quote is findable by exact span", SENTENCE in OUT)
# find(), not index(): a truncating regression must FAIL this check, not crash
# the file and skip every check below it.
_at = OUT.find(SENTENCE)
check("span offsets round-trip", OUT[_at:_at + len(SENTENCE)] if _at >= 0 else None, SENTENCE)
check_true("chrome is gone", "Home" not in OUT and "copyright" not in OUT)
check_true("speaker label is kept", "CEO:" in OUT)

# --- assert_verbatim ---------------------------------------------------------

assert_verbatim(PAGE, OUT)
CHECKS += 1
assert_verbatim("<p>foo<b>bar</b></p>", html_to_text("<p>foo<b>bar</b></p>"))
CHECKS += 1
assert_verbatim("<p>a</p><p>b</p>", html_to_text("<p>a</p><p>b</p>"))
CHECKS += 1

# A truncating extractor must be caught. This is the failure mode the guard
# exists for: a page half-read reads as a low-yield source, not as a bug.
check_raises("truncation is caught", lambda: assert_verbatim(PAGE, OUT[:40]))
check_raises("invented text is caught", lambda: assert_verbatim(PAGE, OUT + " plus invented words"))
check_raises("reordered text is caught", lambda: assert_verbatim("<p>alpha</p><p>beta</p>", "beta\n\nalpha"))

check("letter stream ignores whitespace", letter_stream("a b\nc"), letter_stream("abc"))
check("letter stream ignores punctuation", letter_stream("Q1, 2026!"), "q12026")

# --- real-world shapes -------------------------------------------------------

FOOL = (
    "<div class='article-body'><p><strong>Operator</strong></p>"
    "<p>Good afternoon.</p><p><strong>Lip-Bu Tan -- Chief Executive Officer</strong></p>"
    "<p>We expect revenue to exceed $20 billion in fiscal 2027.</p></div>"
)
f_out = html_to_text(FOOL)
assert_verbatim(FOOL, f_out)
CHECKS += 1
check_true("earnings quote grounds",
           "We expect revenue to exceed $20 billion in fiscal 2027." in f_out)
check_true("speaker attribution survives", "Chief Executive Officer" in f_out)

# A page whose body sits inside <main> rather than <article>.
MAIN = "<main><section><p>We will ship it by June 2027.</p></section></main>"
check_true("main and section are blocks", "We will ship it by June 2027." in html_to_text(MAIN))

# Malformed HTML must not raise; these pages are not well-formed in the wild.
check_true("unclosed tags survive", "keep" in html_to_text("<p>keep<div><span>more"))
check_true("stray close tag survives", "keep" in html_to_text("</div><p>keep</p>"))
check("empty document", html_to_text(""), "")

print(f"test_web_source_text: {CHECKS} checks, {len(FAILED)} failed")
for f in FAILED:
    print("  FAIL " + f)
sys.exit(1 if FAILED else 0)
