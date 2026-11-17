"""What the model sees of a fetched page: the text, or a pointer to it.

A single page can be a megabyte of article. The output budget
(:mod:`agent.tools.token_budget`) already decides when a tool result is too large,
and the rest of the toolset answers that by writing the full text to the run's
scratch directory and returning a preview plus the path. A fetch uses the same
contract, so "too large" looks familiar instead of being a special case:

* the text is persisted as ``.md`` (it *is* Markdown-style text) under
  ``ToolBindings.output_directory``, which ``read_file`` can read but never write;
* the preview is sized from the budget rather than fixed, so a small budget still
  leaves a usable preview instead of a 2,000-character result that is itself over
  budget;
* a binary body is written byte-for-byte and reported by path - a PDF rendered as
  text would be a lie, and rewriting the bytes would break the file.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from agent.tools.output_store import ensure_dir, new_stem, persist_text, preview
from agent.tools.token_budget import check_text, resolve_max_tokens
from agent.tools.web_fetch.limits import MIN_PREVIEW_CHARS, PERSIST_PREFIX, PREVIEW_CHARS


def preview_chars(max_tokens: int) -> int:
    """How much of a persisted page stays in context.

    Three characters per token is a conservative English ratio; the result stays
    under the budget that triggered the persist, and never shrinks below
    ``MIN_PREVIEW_CHARS`` - a preview that cannot be recognised is not a preview.
    """
    return max(MIN_PREVIEW_CHARS, min(PREVIEW_CHARS, resolve_max_tokens(max_tokens) * 3))


def _persist_text(text: str, directory: Optional[Path]) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(path, error)``; both ``None`` when the run has nowhere to write."""
    if directory is None:
        return None, "this run has no scratch directory"
    try:
        path = persist_text(
            ensure_dir(directory),
            new_stem(PERSIST_PREFIX) + ".md",
            # A NUL byte makes read_file treat the file as binary, which would leave
            # the path this message points at unreadable.
            text.replace("\x00", "\ufffd"),
        )
    except OSError as exc:
        return None, str(exc)
    return path.as_posix(), None


def fit_content(
    text: str,
    *,
    max_tokens: int,
    provider: str = "",
    model: str = "",
    directory: Optional[Path] = None,
) -> Dict[str, Any]:
    """Return the ``content`` fields of the tool result for ``text``."""
    report = check_text(text, max_tokens, provider=provider, model=model)
    if report.ok:
        return {
            "content": text,
            "content_truncated": False,
            "persisted_path": None,
            "original_tokens": report.tokens,
        }

    path, error = _persist_text(text, directory)
    if path:
        where = (
            f"The complete text is saved at {path}; read it back in slices with "
            "read_file (offset/limit; the N<TAB> prefixes are line numbers)."
        )
    else:
        where = (
            f"It could not be saved ({error}), so only this preview is available - "
            "narrow the request, for example by fetching a section of the site."
        )
    headline = (
        f"The page is larger than one tool result returns ({len(text):,} characters, "
        f"about {report.tokens:,} tokens). {where}"
    )
    body = preview(text, preview_chars(max_tokens))
    return {
        "content": f"{headline}\n\n--- preview ---\n{body}",
        "content_truncated": True,
        "persisted_path": path,
        "original_tokens": report.tokens,
    }


def save_binary(
    body: bytes,
    directory: Optional[Path],
    media_type: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Write a binary body unchanged; returns ``(path, error)``."""
    if directory is None:
        return None, "this run has no scratch directory"
    suffix = mimetypes.guess_extension(media_type) or ".bin"
    try:
        path = ensure_dir(directory) / (new_stem(PERSIST_PREFIX) + suffix)
        path.write_bytes(body)
    except OSError as exc:
        return None, str(exc)
    return path.as_posix(), None
