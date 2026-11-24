"""Turning a fetched body into model-readable text.

The response tells us three things that decide the shape of the result: the media
type, the charset, and whether the bytes are text at all. Each is used in that
order:

1. **HTML** goes through :func:`~agent.tools.web_fetch.html_text.html_to_text`.
2. **Other text** (``text/*``, JSON, XML, JavaScript...) is returned as-is, because
   re-wrapping it would only lose information.
3. **Everything else** is binary: the tool saves the bytes and reports the path.

Decoding never fails a fetch. The file tools refuse to guess an encoding because a
wrong guess there means a silently mis-edited file; a fetched page has no such
write path, so the order is charset from the header, byte order mark, UTF-8, the
``charset-normalizer`` candidates, and finally ``latin-1`` with replacement. The
result reports which one was used, so the model can tell when the text looks odd.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from agent.tools.text_encoding import (
    canonical_encoding,
    detect_bom,
    looks_binary,
    suggest_encodings,
)
from agent.tools.web_fetch.fetch import FetchedPage
from agent.tools.web_fetch.html_text import html_to_text

KIND_HTML = "html"
KIND_TEXT = "text"
KIND_BINARY = "binary"

HTML_TYPES = ("text/html", "application/xhtml+xml")

# Non-``text/*`` media types that still carry readable text.
TEXT_APPLICATION_TYPES = frozenset(
    {
        "application/json",
        "application/xml",
        "application/javascript",
        "application/x-javascript",
        "application/ecmascript",
        "application/x-www-form-urlencoded",
        "application/yaml",
        "application/x-yaml",
        "application/sql",
        "application/graphql",
        "application/rtf",
    }
)

_CHARSET = re.compile(r";\s*charset\s*=\s*\"?([^\";]+)", re.IGNORECASE)


@dataclass(frozen=True)
class Extracted:
    """A fetched body in the shape the tool reports."""

    kind: str
    text: str = ""
    title: str = ""
    media_type: str = ""
    encoding: str = ""


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
    """Whether a media type is text we can hand over unchanged."""
    if not media_type:
        # No header at all: sniff the bytes instead of refusing the page.
        return True
    if media_type.startswith("text/"):
        return True
    if media_type.endswith(("+json", "+xml")):
        return True
    return media_type in TEXT_APPLICATION_TYPES


def extract_content(page: FetchedPage) -> Extracted:
    """Classify ``page`` and convert the body when it is HTML."""
    media_type = media_type_of(page.content_type)
    hint = charset_of(page.content_type)
    has_bom = detect_bom(page.body) is not None
    binary = not has_bom and looks_binary(page.body)

    if media_type in HTML_TYPES or (not media_type and looks_like_html(page.body)):
        markup, encoding = decode_body(page.body, hint)
        document = html_to_text(markup, page.url)
        return Extracted(
            kind=KIND_HTML,
            text=document.text,
            title=document.title,
            media_type=media_type or "text/html",
            encoding=encoding,
        )

    if is_textual(media_type) and not binary:
        text, encoding = decode_body(page.body, hint)
        return Extracted(
            kind=KIND_TEXT,
            text=text,
            title=page.title,
            media_type=media_type,
            encoding=encoding,
        )

    return Extracted(kind=KIND_BINARY, media_type=media_type or "application/octet-stream")
