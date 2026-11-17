"""How much of the page the model gets, and what it is told about the rest.

Two bounds apply, in this order, because they answer different questions:

* :func:`clamp` is the reference tool's **character cap**. A page longer than
  50,000 characters is cut and the text ends with ``[truncated]``: the model can
  see that its view is partial without reading a JSON field first.
* :func:`fit_content` is the run's **output token budget**
  (:mod:`agent.tools.token_budget`). Text that still does not fit is written to the
  run's scratch directory and the model gets a preview plus the path - the same
  contract ``web_fetch``, ``web_search`` and ``exec_command`` follow, so a large
  result looks familiar instead of being a special case.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from agent.tools.output_store import ensure_dir, new_stem, persist_text, preview
from agent.tools.token_budget import check_text, resolve_max_tokens
from agent.tools.web_browser.limits import (
    MAX_CONTENT_CHARS,
    MIN_PREVIEW_CHARS,
    PERSIST_PREFIX,
    PREVIEW_CHARS,
    TRUNCATION_MARKER,
)


def clamp(text: str) -> Tuple[str, bool]:
    """Cut ``text`` at :data:`MAX_CONTENT_CHARS`; returns ``(text, capped)``."""
    if len(text) <= MAX_CONTENT_CHARS:
        return text, False
    marker = f"\n{TRUNCATION_MARKER}"
    return text[: MAX_CONTENT_CHARS - len(marker)] + marker, True


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
            new_stem(PERSIST_PREFIX) + ".txt",
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
            "open a narrower page, or use web_fetch for the same text in slices."
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
