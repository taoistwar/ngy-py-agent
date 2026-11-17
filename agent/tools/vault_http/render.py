"""Turning the response bytes into what the model reads.

Two steps, both of which have to be honest about their limits:

* :func:`decode_body` decodes with the charset the server declared, falling back to
  UTF-8. An API answer is JSON by convention (UTF-8 per RFC 8259), so a guess is
  cheap here in a way it is not for a file on disk.
* :func:`fit_body` applies the output token budget. A body that does not fit is
  written to the run's scratch directory and reported as a preview plus a path -
  the same contract ``exec_command`` and ``web_fetch`` use, so "too large" looks
  familiar instead of being a special case.
"""

from __future__ import annotations

import codecs
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from agent.tools.output_store import ensure_dir, new_stem, persist_text, preview
from agent.tools.text_encoding import DEFAULT_ENCODING
from agent.tools.token_budget import check_text, resolve_max_tokens

PERSIST_PREFIX = "vault-"
PREVIEW_CHARS = 2000
MIN_PREVIEW_CHARS = 200

_CHARSET = re.compile(r"charset\s*=\s*\"?([A-Za-z0-9._:-]+)", re.IGNORECASE)


def charset_of(content_type: str) -> Optional[str]:
    """The charset declared in a ``Content-Type`` header, if any."""
    match = _CHARSET.search(str(content_type or ""))
    return match.group(1) if match else None


def decode_body(body: bytes, content_type: str) -> Tuple[str, str]:
    """Return ``(text, encoding)`` for a response body.

    The decoded text is what gets scrubbed and reported, so it must not fail: an
    unknown or unusable charset falls back to UTF-8 with replacement characters
    instead of losing the answer entirely. ``encoding`` reports what was used.
    """
    declared = charset_of(content_type)
    for candidate in (declared, DEFAULT_ENCODING):
        if not candidate:
            continue
        try:
            name = codecs.lookup(candidate).name
        except LookupError:
            continue
        return body.decode(name, errors="replace"), name
    return body.decode(DEFAULT_ENCODING, errors="replace"), DEFAULT_ENCODING


def preview_chars(max_tokens: int) -> int:
    """How much of a persisted body stays in context."""
    return max(MIN_PREVIEW_CHARS, min(PREVIEW_CHARS, resolve_max_tokens(max_tokens) * 3))


def _persist(text: str, directory: Optional[Path]) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(path, error)``; both ``None`` when the run has nowhere to write."""
    if directory is None:
        return None, "this run has no scratch directory"
    try:
        path = persist_text(
            ensure_dir(directory),
            new_stem(PERSIST_PREFIX) + ".txt",
            # A NUL byte would make read_file treat the file as binary, leaving the
            # path this message points at unreadable.
            text.replace("\x00", "\ufffd"),
        )
    except OSError as exc:
        return None, str(exc)
    return path.as_posix(), None


def fit_body(
    text: str,
    *,
    max_tokens: int,
    provider: str = "",
    model: str = "",
    directory: Optional[Path] = None,
) -> Dict[str, Any]:
    """The ``body`` fields of the tool result for ``text``."""
    report = check_text(text, max_tokens, provider=provider, model=model)
    if report.ok:
        return {
            "body": text,
            "body_truncated": False,
            "persisted_path": None,
            "original_tokens": report.tokens,
        }

    path, error = _persist(text, directory)
    if path:
        where = (
            f"The complete body is saved at {path}; read it back in slices with read_file "
            "(offset/limit; the N<TAB> prefixes are line numbers)."
        )
    else:
        where = (
            f"It could not be saved ({error}), so only this preview is available - narrow "
            "the request instead, for example by asking the endpoint for fewer fields."
        )
    headline = (
        f"The response body is larger than one tool result returns ({len(text):,} "
        f"characters, about {report.tokens:,} tokens). {where}"
    )
    return {
        "body": f"{headline}\n\n--- preview ---\n{preview(text, preview_chars(max_tokens))}",
        "body_truncated": True,
        "persisted_path": path,
        "original_tokens": report.tokens,
    }
