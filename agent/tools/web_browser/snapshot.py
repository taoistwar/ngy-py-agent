"""What the model sees of a page: the title, and the words on the page.

This is a *text browser* view, not the structured one ``web_fetch`` produces: blocks
end with a blank line, list items start with ``- `` (nested ones are indented), and
that is all the structure there is. Link targets, code fences and table pipes are
deliberately absent - ``web_fetch`` is the tool for those, and two converters that
both emit Markdown would only be one converter with two names.

What is dropped, for the same reason ``web_fetch`` drops it: the page's furniture.
``nav``, ``footer``, ``role="navigation|banner|contentinfo"``, ``hidden`` and
``aria-hidden="true"`` are chrome, and a page that starts with its menu spends the
first thousand tokens of the model's context on links nobody asked for.

Decoding never fails a navigation: a charset from the header, then the byte order
mark, then UTF-8, then ``charset-normalizer``, then ``latin-1``. A wrong guess on a
read-only page is a cosmetic problem; refusing the page would be a real one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Optional

from agent.tools.text_encoding import (
    canonical_encoding,
    detect_bom,
    looks_binary,
    suggest_encodings,
)
from agent.tools.web_browser.fetch import BrowsedPage

KIND_HTML = "html"
KIND_TEXT = "text"
KIND_BINARY = "binary"

HTML_TYPES = ("text/html", "application/xhtml+xml")

# Non-``text/*`` media types a browser still shows as text.
TEXT_APPLICATION_TYPES = frozenset(
    {
        "application/json",
        "application/xml",
        "application/javascript",
        "application/x-javascript",
        "application/yaml",
        "application/x-yaml",
        "application/sql",
    }
)

_WHITESPACE = re.compile(r"\s+")
_CHARSET = re.compile(r";\s*charset\s*=\s*\"?([^\";]+)", re.IGNORECASE)

# Elements whose content is never page text. ``head`` is not here: the ``<title>``
# inside it is captured separately.
_SKIP_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "canvas",
        "iframe",
        "object",
        "embed",
        "select",
        "option",
        "textarea",
        "button",
        "nav",
        "footer",
    }
)

_SKIP_ROLES = frozenset({"navigation", "banner", "contentinfo"})

# Tags that sit on a line of their own; both sides get a blank line, and the final
# pass collapses the runs.
_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "header",
        "main",
        "aside",
        "figure",
        "figcaption",
        "form",
        "fieldset",
        "legend",
        "address",
        "details",
        "summary",
        "dl",
        "dt",
        "dd",
        "blockquote",
        "table",
        "thead",
        "tbody",
        "tfoot",
        "caption",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
    }
)

# Tags that start a new line but not a new paragraph: a blank line between two
# consecutive list items, or between two table rows, is noise a text browser never
# produced.
_LINE_TAGS = frozenset({"li", "tr", "dt", "dd"})

_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

_BULLET = "- "
_INDENT = "  "


@dataclass(frozen=True)
class Snapshot:
    """The page as text, plus the ``<title>`` it came from."""

    kind: str
    text: str = ""
    title: str = ""
    media_type: str = ""
    encoding: str = ""


class _PlainText(HTMLParser):
    """Streaming text extractor: every callback appends to ``self._parts``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list = []
        self._pending_breaks = 0
        self._pending_space = False
        self._skip_stack: list = []
        self._pre_depth = 0
        self._lists: list = []
        self._title_parts: list = []
        self._in_title = False

    # ------------------------------------------------------------------ output

    def title_text(self) -> str:
        return _WHITESPACE.sub(" ", " ".join(self._title_parts)).strip()

    def finish(self) -> str:
        text = "".join(self._parts)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # ------------------------------------------------------------- primitives

    def _flush_breaks(self) -> None:
        if not self._pending_breaks:
            return
        if self._parts:
            self._parts.append("\n" * self._pending_breaks)
        self._pending_breaks = 0
        self._pending_space = False

    def _break(self, count: int = 2) -> None:
        self._pending_breaks = max(self._pending_breaks, count)
        self._pending_space = False

    def _append(self, text: str) -> None:
        if not text:
            return
        self._flush_breaks()
        if self._pending_space and self._parts and not self._parts[-1].endswith((" ", "\n")):
            self._parts.append(" ")
        self._pending_space = False
        self._parts.append(text)

    def _text(self, raw: str) -> None:
        collapsed = _WHITESPACE.sub(" ", raw)
        if not collapsed:
            return
        # Leading whitespace belongs to whatever comes next, trailing whitespace to
        # the chunk after this one - so the flag is read *and* set here.
        if collapsed.startswith(" "):
            self._pending_space = True
        body = collapsed.strip()
        if body:
            self._append(body)
        if collapsed.endswith(" "):
            self._pending_space = True

    # ---------------------------------------------------------------- parsing

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "title" and not self._skip_stack:
            self._in_title = True
            self._title_parts.clear()
            return

        if self._skip_stack:
            if tag not in _VOID_TAGS:
                self._skip_stack.append(tag)
            return

        if tag in _SKIP_TAGS or _hidden(attrs) or _is_chrome(attrs):
            if tag not in _VOID_TAGS:
                self._skip_stack.append(tag)
            return

        if tag == "br":
            self._break(1)
        elif tag == "pre":
            self._break(2)
            self._pre_depth += 1
        elif tag in ("ul", "ol"):
            self._break(1)
            self._lists.append(tag)
        elif tag == "li":
            self._list_item()
        elif tag in ("td", "th"):
            # Cells stay on one line; a space is the separator a text browser uses.
            self._pending_space = True
        elif tag == "img":
            self._image(attrs)
        elif tag in _LINE_TAGS:
            self._break(1)
        elif tag in _BLOCK_TAGS:
            self._break(2)

    def handle_startendtag(self, tag: str, attrs) -> None:
        # ``<div hidden/>`` has no content, so it must not open a skip frame.
        if tag in _VOID_TAGS:
            if not self._skip_stack:
                if tag == "br":
                    self._break(1)
                elif tag == "img":
                    self._image(attrs)
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        # Mirrors ``handle_starttag``: only a title outside a skipped element is the
        # page title. An ``<svg><title>`` must fall through to the skip stack.
        if tag == "title" and not self._skip_stack:
            self._in_title = False
            return

        if self._skip_stack:
            self._leave_skipped(tag)
            return

        if tag == "pre":
            self._pre_depth = max(0, self._pre_depth - 1)
            self._break(2)
        elif tag in ("ul", "ol"):
            if self._lists:
                self._lists.pop()
            self._break(1)
        elif tag in _LINE_TAGS:
            self._break(1)
        elif tag in _BLOCK_TAGS:
            self._break(2)

    def handle_data(self, data: str) -> None:
        if self._skip_stack:
            return
        if self._in_title:
            self._title_parts.append(data)
            return
        if self._pre_depth:
            # Indentation and line breaks are the content of a code sample.
            self._append(data)
            return
        self._text(data)

    # ----------------------------------------------------------------- pieces

    def _list_item(self) -> None:
        depth = max(0, len(self._lists) - 1)
        self._flush_breaks()
        if self._parts and not self._parts[-1].endswith("\n"):
            self._parts.append("\n")
        self._pending_space = False
        self._parts.append(f"{_INDENT * depth}{_BULLET}")

    def _image(self, attrs) -> None:
        alt = (_attr(attrs, "alt") or "").strip()
        if alt:
            self._append(alt)

    def _leave_skipped(self, tag: str) -> None:
        """Close ``tag`` inside a skipped element, tolerating unclosed markup."""
        if tag not in self._skip_stack:
            return
        index = len(self._skip_stack) - 1 - self._skip_stack[::-1].index(tag)
        del self._skip_stack[index:]


def _attr(attrs, name: str) -> Optional[str]:
    for key, value in attrs:
        if key == name:
            return value
    return None


def _hidden(attrs) -> bool:
    for key, value in attrs:
        if key == "hidden":
            return True
        if key == "aria-hidden" and (value or "").strip().lower() == "true":
            return True
    return False


def _is_chrome(attrs) -> bool:
    """Whether an element declares itself as navigation or page furniture."""
    return (_attr(attrs, "role") or "").strip().lower() in _SKIP_ROLES


def _fallback_text(markup: str) -> str:
    stripped = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", markup)
    stripped = re.sub(r"(?s)<[^>]+>", " ", stripped)
    return _WHITESPACE.sub(" ", unescape(stripped)).strip()


def html_to_snapshot(markup: str) -> Snapshot:
    """Convert ``markup`` to a text snapshot. Never raises."""
    parser = _PlainText()
    try:
        parser.feed(markup)
        parser.close()
        text = parser.finish()
    except Exception:  # noqa: BLE001 - a page that already loaded must not fail here
        return Snapshot(kind=KIND_HTML, text=_fallback_text(markup))
    return Snapshot(kind=KIND_HTML, text=text, title=parser.title_text())


def media_type_of(header: str) -> str:
    """``"text/html; charset=utf-8"`` -> ``"text/html"``."""
    return (header or "").split(";", 1)[0].strip().lower()


def charset_of(header: str) -> Optional[str]:
    match = _CHARSET.search(header or "")
    return match.group(1).strip() if match else None


def decode_body(body: bytes, hint: Optional[str] = None) -> tuple[str, str]:
    """Decode ``body`` as faithfully as possible; returns ``(text, encoding)``."""
    bom = detect_bom(body)
    if bom is not None:
        bom_bytes, bom_encoding = bom
        return body[len(bom_bytes) :].decode(bom_encoding, errors="replace"), bom_encoding

    if hint:
        try:
            encoding = canonical_encoding(hint)
            return body.decode(encoding), encoding
        except (LookupError, UnicodeDecodeError):
            pass

    try:
        return body.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    for candidate in suggest_encodings(body):
        name = candidate["encoding"]
        if name in ("utf-8", "latin-1"):
            # utf-8 just failed; latin-1 accepts anything, so neither is a guess.
            continue
        try:
            return body.decode(name), name
        except (LookupError, UnicodeDecodeError):
            continue

    return body.decode("latin-1", errors="replace"), "latin-1"


def looks_like_html(body: bytes) -> bool:
    head = body[:1024].lstrip().lower()
    return head.startswith(b"<!doctype html") or b"<html" in head


def is_textual(media_type: str) -> bool:
    """Whether a media type is text a browser would show instead of downloading."""
    if not media_type:
        # No header at all: sniff the bytes instead of refusing the page.
        return True
    if media_type.startswith("text/"):
        return True
    if media_type.endswith(("+json", "+xml")):
        return True
    return media_type in TEXT_APPLICATION_TYPES


def snapshot_page(page: BrowsedPage) -> Snapshot:
    """Classify ``page`` and turn its body into the text view."""
    media_type = media_type_of(page.content_type)
    hint = charset_of(page.content_type)
    binary = detect_bom(page.body) is None and looks_binary(page.body)

    if media_type in HTML_TYPES or (not media_type and looks_like_html(page.body)):
        markup, encoding = decode_body(page.body, hint)
        snapshot = html_to_snapshot(markup)
        return Snapshot(
            kind=KIND_HTML,
            text=snapshot.text,
            title=snapshot.title,
            media_type=media_type or "text/html",
            encoding=encoding,
        )

    if is_textual(media_type) and not binary:
        text, encoding = decode_body(page.body, hint)
        return Snapshot(
            kind=KIND_TEXT, text=text, media_type=media_type, encoding=encoding
        )

    return Snapshot(kind=KIND_BINARY, media_type=media_type or "application/octet-stream")
