"""HTML to Markdown-style text: enough structure for a model, nothing else.

The model reads this instead of the markup, so the conversion has one job: keep
what carries meaning (headings, paragraphs, lists, links, code, table rows) and
drop what does not (scripts, styles, hidden elements, form controls, and site
chrome such as ``<nav>`` and ``<footer>``). It is lossy on purpose - a perfect
HTML-to-Markdown converter is a dependency, and this is a few hundred lines of
``html.parser``.

Deliberate choices, each of which shows up in the tests:

* **Links keep their target** (``[text](url)``) because "the download page" is
  usually a link to follow, not a sentence to read. Relative targets resolve
  against the URL that was fetched. ``javascript:``, ``mailto:`` and ``#anchor``
  links degrade to their text: they cannot be fetched, so a URL would only
  mislead.
* **Code blocks are fenced and keep their whitespace** - indentation is the
  content of a code sample - while everything else collapses runs of spaces.
* **Table rows survive as pipe rows**, without a header separator: the separator
  is decoration, and a model that sees a two-column row reads it either way.
* **An empty inline marker is dropped** (``<b></b>`` must not leave ``****``).
* **The page title becomes the first heading** when the body does not already
  start with it; a page that never says what it is, is a page the model
  summarises badly.
* **A parser crash falls back to tag stripping.** Returning slightly worse text
  beats failing a fetch that already succeeded.

The converter never raises: :func:`html_to_text` always returns text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin, urlsplit

_WHITESPACE = re.compile(r"\s+")

# Elements whose content is never page text. ``head`` is *not* here: only the title
# inside it is interesting, and it is captured separately.
#
# ``nav`` and ``footer`` are skipped because they are site chrome by definition:
# a page that survives the trip to the model should not spend its first thousand
# tokens on the menu. ``role`` values below cover the same intent on pages that
# predate the semantic elements (Sphinx, for one, marks its sidebar
# ``role="navigation"``).
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

_HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

# Tags that start and end a block of their own. They break the line on both sides;
# repeated blank lines are collapsed at the end.
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
    }
)

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

_EMPHASIS = {"b": "**", "strong": "**", "i": "*", "em": "*"}

_BULLET = "- "
_INDENT = "  "


@dataclass(frozen=True)
class PageText:
    """Converted page text plus the ``<title>`` it came from."""

    text: str
    title: str = ""


@dataclass
class _Mark:
    """An open inline marker, and where it started in ``parts``."""

    kind: str
    text: str
    index: int
    # A link opens with ``[`` and closes with ``]``; every other marker uses the
    # same string on both sides.
    closer: str = ""
    # Only used by links: the resolved target, or ``None`` for a link that cannot
    # be followed (``mailto:``, ``#anchor``, a relative target with no base).
    target: Optional[str] = None


class _Converter(HTMLParser):
    """Streaming converter: every callback appends to ``self._parts``."""

    def __init__(self, base_url: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._parts = []
        self._pending_breaks = 0
        self._pending_space = False
        self._skip_stack = []
        self._pre_depth = 0
        self._pre_parts = []
        self._title_parts = []
        self._in_title = False
        self._lists = []
        self._markers = []
        self._cell_depth = 0
        self._in_row = False
        self._row_open = False

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

    def _break(self, count: int = 1) -> None:
        if self._cell_depth:
            # A block inside a table cell would break the row apart; a space keeps
            # the cell readable.
            self._pending_space = True
            return
        self._pending_breaks = max(self._pending_breaks, count)
        self._pending_space = False

    def _start_line(self) -> None:
        self._flush_breaks()
        if self._parts and not self._parts[-1].endswith("\n"):
            self._parts.append("\n")
        self._pending_space = False

    def _inline(self, text: str) -> None:
        if not text:
            return
        self._flush_breaks()
        if (
            self._pending_space
            and self._parts
            and not self._parts[-1].endswith((" ", "\n"))
        ):
            self._parts.append(" ")
        self._pending_space = False
        self._parts.append(text)

    def _text(self, raw: str) -> None:
        collapsed = _WHITESPACE.sub(" ", raw)
        if not collapsed:
            return
        # Leading whitespace is owed to whatever comes next, trailing whitespace to
        # the chunk after this one - so the flag is read *and* set here.
        if collapsed.startswith(" "):
            self._pending_space = True
        body = collapsed.strip()
        if body:
            self._inline(body)
        if collapsed.endswith(" "):
            self._pending_space = True

    def _open_marker(
        self,
        kind: str,
        marker: str,
        *,
        closer: str = "",
        target: Optional[str] = None,
    ) -> None:
        self._flush_breaks()
        if (
            self._pending_space
            and self._parts
            and not self._parts[-1].endswith((" ", "\n"))
        ):
            self._parts.append(" ")
        self._pending_space = False
        self._markers.append(
            _Mark(
                kind=kind,
                text=marker,
                index=len(self._parts),
                closer=closer,
                target=target,
            )
        )
        self._parts.append(marker)

    def _close_marker(self, kind: str) -> Optional[_Mark]:
        """Close the nearest marker of ``kind``; ``None`` when it rendered nothing."""
        while self._markers:
            mark = self._markers.pop()
            if mark.kind != kind:
                # An opener whose end tag never arrived. Dropping it beats closing
                # the wrong marker - and ``****`` in the output.
                if len(self._parts) == mark.index + 1:
                    del self._parts[mark.index]
                continue
            if len(self._parts) == mark.index + 1:
                del self._parts[mark.index]
                return None
            self._parts.append(mark.closer or mark.text)
            return mark
        return None

    def _resolve(self, target: Optional[str]) -> Optional[str]:
        value = (target or "").strip()
        if not value or value.startswith("#"):
            return None
        try:
            absolute = urljoin(self.base_url, value)
        except ValueError:
            return None
        if urlsplit(absolute).scheme.lower() not in ("http", "https"):
            return None
        return absolute

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

        if tag in _SKIP_TAGS or _is_hidden(attrs) or _is_chrome(attrs):
            if tag not in _VOID_TAGS:
                self._skip_stack.append(tag)
            return

        if tag == "br":
            self._break(1)
        elif tag == "hr":
            self._break(2)
            self._inline("---")
            self._break(2)
        elif tag in _HEADING_LEVELS:
            self._break(2)
            self._inline("#" * _HEADING_LEVELS[tag] + " ")
        elif tag in ("ul", "ol"):
            self._break(1)
            self._lists.append((tag, 0))
        elif tag == "li":
            self._break(1)
            self._list_item()
        elif tag == "tr":
            self._start_line()
            self._in_row = True
            self._row_open = False
        elif tag in ("td", "th"):
            if not self._in_row:
                self._start_line()
                self._in_row = True
            self._flush_breaks()
            self._parts.append("| " if not self._row_open else " | ")
            self._row_open = True
            self._cell_depth += 1
        elif tag == "pre":
            self._break(2)
            self._pre_depth += 1
            self._pre_parts.clear()
        elif tag == "code":
            if not self._pre_depth:
                self._open_marker("code", "`")
        elif tag == "a":
            # The target travels with the marker, so ``</a>`` needs no attributes.
            target = self._resolve(_attr(attrs, "href"))
            if target:
                self._open_marker("link", "[", closer="]", target=target)
            else:
                # A link that cannot be fetched is only its text: ``[mail]`` would
                # look like a broken link rather than a ``mailto:`` address.
                self._open_marker("link", "")
        elif tag == "img":
            self._image(attrs)
        elif tag in _EMPHASIS:
            self._open_marker("em", _EMPHASIS[tag])
        elif tag in _BLOCK_TAGS:
            self._break(2)

    def handle_startendtag(self, tag: str, attrs) -> None:
        # ``<div hidden/>`` has no content, so it must not open a skip frame.
        if tag in _VOID_TAGS:
            if not self._skip_stack:
                if tag == "br":
                    self._break(1)
                elif tag == "hr":
                    self._break(2)
                    self._inline("---")
                    self._break(2)
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

        if tag in _HEADING_LEVELS:
            self._break(2)
        elif tag in ("ul", "ol"):
            if self._lists:
                self._lists.pop()
            self._break(1)
        elif tag == "li":
            self._break(1)
        elif tag == "tr":
            if self._row_open:
                self._parts.append(" |")
            self._row_open = False
            self._in_row = False
            self._break(1)
        elif tag in ("td", "th"):
            self._cell_depth = max(0, self._cell_depth - 1)
        elif tag == "pre":
            self._pre_depth = max(0, self._pre_depth - 1)
            if self._pre_depth == 0:
                self._flush_fence()
        elif tag == "code":
            if not self._pre_depth:
                self._close_marker("code")
        elif tag == "a":
            mark = self._close_marker("link")
            if mark is not None and mark.target:
                self._parts.append(f"({mark.target})")
        elif tag in _EMPHASIS:
            self._close_marker("em")
        elif tag in _BLOCK_TAGS:
            self._break(2)

    def handle_data(self, data: str) -> None:
        if self._skip_stack:
            return
        if self._in_title:
            self._title_parts.append(data)
            return
        if self._pre_depth:
            self._pre_parts.append(data)
            return
        self._text(data)

    # ----------------------------------------------------------------- pieces

    def _list_item(self) -> None:
        depth = max(0, len(self._lists) - 1)
        marker = _BULLET
        if self._lists and self._lists[-1][0] == "ol":
            kind, count = self._lists[-1]
            count += 1
            self._lists[-1] = (kind, count)
            marker = f"{count}. "
        self._flush_breaks()
        if self._parts and not self._parts[-1].endswith("\n"):
            self._parts.append("\n")
        self._pending_space = False
        self._parts.append(_INDENT * depth + marker)

    def _image(self, attrs) -> None:
        alt = (_attr(attrs, "alt") or "").strip()
        src = self._resolve(_attr(attrs, "src"))
        if src:
            self._inline(f"![{alt}]({src})")
        elif alt:
            self._inline(alt)

    def _flush_fence(self) -> None:
        block = "".join(self._pre_parts)
        self._pre_parts.clear()
        block = block.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
        self._flush_breaks()
        self._parts.append("```\n" + block + "\n```")
        self._break(2)

    def _leave_skipped(self, tag: str) -> None:
        """Close ``tag`` inside a skipped element, tolerating unclosed markup.

        A skipped element can contain anything, including tags that never close
        (``<p>`` without ``</p>``). Popping up to the innermost occurrence keeps
        the stack finite and lets the rest of the page through again.
        """
        if tag not in self._skip_stack:
            return
        index = len(self._skip_stack) - 1 - self._skip_stack[::-1].index(tag)
        del self._skip_stack[index:]


def _attr(attrs, name: str) -> Optional[str]:
    for key, value in attrs:
        if key == name:
            return value
    return None


def _is_hidden(attrs) -> bool:
    for key, value in attrs:
        if key == "hidden":
            return True
        if key == "aria-hidden" and (value or "").strip().lower() == "true":
            return True
    return False


def _is_chrome(attrs) -> bool:
    """Whether an element declares itself as navigation or page furniture."""
    role = (_attr(attrs, "role") or "").strip().lower()
    return role in _SKIP_ROLES


def _fallback_text(markup: str) -> str:
    stripped = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", markup)
    stripped = re.sub(r"(?s)<[^>]+>", " ", stripped)
    return re.sub(r"\s+", " ", unescape(stripped)).strip()


def _title_heading(text: str, title: str) -> str:
    """Prepend ``# title`` unless the body already opens with that heading."""
    if not title:
        return text
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first.startswith("# ") and title.lower() in first.lower():
        return text
    heading = f"# {title}"
    return f"{heading}\n\n{text}" if text else heading


def html_to_text(markup: str, base_url: str = "") -> PageText:
    """Convert ``markup`` to text. Never raises: a parser crash falls back to tags."""
    parser = _Converter(base_url)
    try:
        parser.feed(markup)
        parser.close()
        text = parser.finish()
    except Exception:  # noqa: BLE001 - a fetch that already succeeded must not fail here
        return PageText(text=_fallback_text(markup))
    title = parser.title_text()
    return PageText(text=_title_heading(text, title), title=title)
