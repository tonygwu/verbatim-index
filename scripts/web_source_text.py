"""Turn a fetched HTML page into verbatim plain text.

Why stdlib only: requirements.txt is pinned to what repo-0 ran the published
grades with, and a text extractor is not worth diverging every clone's
environment over. html.parser is in the standard library and is enough for the
page shapes this pipeline reads, which are earnings-call transcripts, testimony
and printed interviews: long runs of <p> inside one container.

THE VERBATIM RULE. Downstream, ground_candidates() finds each model-proposed
quote by an EXACT span match against this text and records character offsets.
A quote that does not match exactly is dropped, never repaired. So this module
may do exactly two things to the words: unescape HTML entities, and normalise
whitespace. It must never reflow, re-punctuate, de-hyphenate, transliterate or
drop a word. `assert_verbatim()` is the guard, and test_web_source_text.py
exercises it.

Whitespace normalisation is itself a risk. Collapsing "a\n b" to "a b" changes
character offsets but not words, which is fine, because offsets are computed
against THIS output and never against the original HTML.
"""

from __future__ import annotations

import html as html_mod
import json
import re
import unicodedata
from html.parser import HTMLParser

# Tags whose text is never part of the document body.
DROP_TAGS = {
    "script", "style", "noscript", "template", "svg", "canvas", "iframe",
    "nav", "header", "footer", "aside", "form", "button", "select", "option",
    "figure", "figcaption",
}

# Tags that force a paragraph break around their content.
BLOCK_TAGS = {
    "p", "div", "section", "article", "main", "blockquote", "pre",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "ul", "ol", "dl", "dt", "dd",
    "table", "thead", "tbody", "tr", "td", "th",
    "hr", "address", "details", "summary",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._drop_depth = 0
        # Tag names we are inside, to reopen a drop correctly on nested tags.
        self._drop_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if self._drop_depth:
            if tag in DROP_TAGS:
                self._drop_stack.append(tag)
                self._drop_depth += 1
            return
        if tag in DROP_TAGS:
            self._drop_stack.append(tag)
            self._drop_depth = 1
            return
        if tag == "br":
            self.parts.append("\n")
        elif tag in BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if self._drop_depth:
            if self._drop_stack and self._drop_stack[-1] == tag:
                self._drop_stack.pop()
                self._drop_depth -= 1
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._drop_depth:
            return
        self.parts.append(data)


def _strip_comments(raw: str) -> str:
    return re.sub(r"<!--.*?-->", " ", raw, flags=re.DOTALL)


def html_to_text(raw: str) -> str:
    """Verbatim plain text from an HTML document.

    Entities are unescaped and whitespace is normalised. No word is altered.
    """
    parser = _TextExtractor()
    parser.feed(_strip_comments(raw))
    parser.close()
    text = "".join(parser.parts)
    # convert_charrefs handles most entities; catch any the parser passed through.
    text = html_mod.unescape(text)
    # Normalise unicode so a quote matched later compares byte-for-byte with
    # itself. NFC only, which composes accents and changes no letter.
    text = unicodedata.normalize("NFC", text)
    # Non-breaking and other exotic spaces become an ordinary space. These are
    # whitespace, so this does not alter a word.
    text = text.translate({
        0x00A0: " ", 0x2007: " ", 0x202F: " ", 0x2009: " ", 0x200A: " ",
        0x2002: " ", 0x2003: " ", 0xFEFF: None, 0x200B: None, 0x00AD: None,
    })
    # Collapse horizontal runs inside a line, then vertical runs between lines.
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def words(text: str) -> list[str]:
    """Word tokens, for the verbatim check. Punctuation and case are ignored."""
    return [m.group(0).casefold() for m in _WORD.finditer(text)]


def letter_stream(text: str) -> str:
    """Every alphanumeric character, in order, case-folded.

    Whitespace and punctuation are dropped, so this is insensitive to WHERE a
    tag put a line break and sensitive to whether any text was lost.
    """
    return "".join(_WORD.findall(text)).casefold()


def assert_verbatim(raw_html: str, text: str) -> None:
    """Fail if extraction dropped or invented text, against a naive strip.

    The naive strip is a deliberately different implementation: remove dropped
    elements, then remove every remaining tag. The two are compared on the
    LETTER STREAM rather than on word tokens, because the two implementations
    legitimately disagree about whitespace. A naive strip turns `foo<b>bar</b>`
    into two tokens and this parser into one, and neither is wrong. What neither
    may do is lose a character.

    This is the accept-and-guess guard. A page truncated by a parser quirk would
    otherwise ground zero quotes and read as a low-yield source rather than as
    the bug it is.
    """
    naive = _strip_comments(raw_html)
    for tag in DROP_TAGS:
        naive = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}\s*>", " ", naive,
                       flags=re.DOTALL | re.IGNORECASE)
    # A tag ends at the first ">" OUTSIDE a quoted attribute value. The earlier
    # `<[^>]+>` ended it at the first ">" anywhere, so a page that carries JSON
    # in an attribute (huggingface.co's data-props, cnn.com's data-* image
    # sources) leaked the rest of that attribute into the naive text and the
    # guard refused a correct extraction: 4,575 letters extracted against 14,485
    # "naive" on a Hugging Face post, found 2026-09-27. Still a different
    # implementation from html.parser, which is the point of the check.
    naive = re.sub(r"""<(?:[^>"']|"[^"]*"|'[^']*')*>""", " ", naive)
    naive = unicodedata.normalize("NFC", html_mod.unescape(naive))

    got, want = letter_stream(text), letter_stream(naive)
    if got == want:
        return
    # Locate the first divergence so the message names the place, not a count.
    i = 0
    while i < min(len(got), len(want)) and got[i] == want[i]:
        i += 1
    raise ValueError(
        f"extraction is not verbatim: diverges at character {i} of the letter "
        f"stream ({len(got)} extracted against {len(want)} naive). "
        f"extracted={got[max(0, i - 40):i + 40]!r} naive={want[max(0, i - 40):i + 40]!r}"
    )


# ---------------------------------------------------------------------------
# Next.js pages whose body text lives in embedded script data
# ---------------------------------------------------------------------------
#
# palantir.com shareholder letters are Next.js pages. The server sends a 7-word
# shell, and the letter itself travels in `<script id="__NEXT_DATA__">` as
# Contentful rich-text documents, which a browser renders client-side.
# html_to_text rightly drops every <script>, so the page reads as nav furniture
# and fails MIN_WORDS. A reader service did not help for three of the four
# letters: it served the same unrendered shell.
#
# This reads the rich-text documents directly. It concatenates the `value` of
# every text node inside each top-level block and separates blocks with a blank
# line. That is the same "unescape and normalise whitespace, nothing else" rule
# as html_to_text: the values are the author's own strings, decoded by the
# standard-library JSON parser. Marks (italic, bold) carry no letters and are
# ignored. Plain string fields outside a rich-text document, such as a page
# title, are not body text and are not read.

_NEXT_DATA = re.compile(
    r'<script[^>]*\bid="__NEXT_DATA__"[^>]*>(.*?)</script\s*>', re.DOTALL | re.IGNORECASE)


def _richtext_value(node) -> str:
    if not isinstance(node, dict):
        return ""
    if node.get("nodeType") == "text":
        return node.get("value") or ""
    return "".join(_richtext_value(c) for c in node.get("content") or [])


def _walk(x, visit) -> None:
    if isinstance(x, dict):
        if visit(x):
            return
        for v in x.values():
            _walk(v, visit)
    elif isinstance(x, list):
        for v in x:
            _walk(v, visit)


def next_data_richtext(raw_html: str) -> str | None:
    """Body text from Contentful rich-text documents in __NEXT_DATA__, or None.

    None means the page carries no such data, which is not an error. The
    content read is `props.pageProps.page` only: the same documents are repeated
    under `props.pageProps.metadata.page`, and reading both would print the
    letter twice.

    SELF-CHECK, the counterpart of assert_verbatim. The rendered text is
    compared, on the letter stream, with every text node found ANYWHERE in the
    page subtree by a flat walk that knows nothing about blocks or documents.
    If the renderer missed a text node, for example one held under a key other
    than `content`, the two differ and this raises rather than returning a
    letter with a hole in it.
    """
    m = _NEXT_DATA.search(raw_html)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except ValueError as exc:
        raise ValueError(f"__NEXT_DATA__ is not valid JSON: {exc}") from exc
    page = ((data.get("props") or {}).get("pageProps") or {}).get("page")
    if not isinstance(page, dict):
        return None

    blocks: list[str] = []

    def take_document(node) -> bool:
        if node.get("nodeType") == "document":
            blocks.extend(_richtext_value(b) for b in node.get("content") or [])
            return True
        return False

    _walk(page, take_document)
    if not blocks:
        return None

    flat: list[str] = []

    def take_text(node) -> bool:
        if node.get("nodeType") == "text":
            flat.append(node.get("value") or "")
            return True
        return False

    _walk(page, take_text)

    text = "\n\n".join(b for b in blocks if b.strip())
    text = unicodedata.normalize("NFC", text)
    text = text.translate({
        0x00A0: " ", 0x2007: " ", 0x202F: " ", 0x2009: " ", 0x200A: " ",
        0x2002: " ", 0x2003: " ", 0xFEFF: None, 0x200B: None, 0x00AD: None,
    })
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    got = letter_stream(text)
    want = letter_stream(unicodedata.normalize("NFC", " ".join(flat)))
    if got != want:
        i = 0
        while i < min(len(got), len(want)) and got[i] == want[i]:
            i += 1
        raise ValueError(
            f"__NEXT_DATA__ rich text is not verbatim: diverges at character {i} "
            f"({len(got)} rendered against {len(want)} text nodes). "
            f"rendered={got[max(0, i - 40):i + 40]!r} nodes={want[max(0, i - 40):i + 40]!r}")
    return text
