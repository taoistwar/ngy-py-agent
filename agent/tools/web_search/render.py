"""What the model reads: a short, citable list - or a pointer to the full one.

A search result is consumed as prose, not as a data structure: the model scans it
once and then quotes from it. So the primary field is ``content``, a Markdown
list of linked titles with their snippets, and the structured ``results`` array
travels beside it for the UI.

The list is bounded twice, and both bounds are reported rather than applied
silently:

* ``context_max_characters`` (the caller's own limit) drops the tail of a long
  result list; ``context_truncated`` says how many hits were left out, because a
  model that thinks it saw everything will answer as if it had;
* the run's output token budget is the second net - a caller who asks for 50,000
  characters on a run budgeted smaller would otherwise get a result the loop has
  to shrink afterwards. Oversized text is persisted under the run's scratch
  directory and the model gets a preview plus the path, exactly like
  ``web_fetch`` and ``exec_command``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agent.tools.output_store import ensure_dir, new_stem, persist_text, preview
from agent.tools.token_budget import check_text, resolve_max_tokens
from agent.tools.web_search.hits import SearchHit
from agent.tools.web_search.limits import MIN_PREVIEW_CHARS, PERSIST_PREFIX, PREVIEW_CHARS

# The reference tool's wording, kept: an empty result set is an answer, not a
# failure, and retrying the same query only costs a step.
NO_RESULTS_TEXT = (
    "No search results found. Try a different or shorter query; do not repeat the "
    "same search."
)
FILTERED_OUT_TEXT = (
    "Every result was removed by the domain filter. Widen 'allowed_domains', narrow "
    "'blocked_domains', or drop the filter and search again."
)

CITATION_REMINDER = (
    "Cite the sources you use: give each claim a Markdown link to the result it came "
    "from."
)


@dataclass(frozen=True)
class Rendered:
    """The list that fits, and how many hits did not."""

    content: str
    hits: Tuple[SearchHit, ...]
    dropped: int = 0

    @property
    def truncated(self) -> bool:
        return self.dropped > 0


def _block(hit: SearchHit, index: int) -> str:
    line = f"{index}. [{hit.title}]({hit.url})"
    if hit.snippet:
        return f"{line}\n   {hit.snippet}"
    return line


def _header(query: str, provider: str, count: int) -> str:
    return f'Search results for "{query}" via {provider} ({count} shown):'


def _compose(query: str, provider: str, hits: Sequence[SearchHit], dropped: int) -> str:
    lines = [_header(query, provider, len(hits))]
    lines.extend(_block(hit, index) for index, hit in enumerate(hits, start=1))
    if dropped:
        lines.append(
            f"\n[... {dropped} more result(s) were dropped to stay within "
            "context_max_characters]"
        )
    lines.append("")
    lines.append(CITATION_REMINDER)
    return "\n".join(lines)


def render_results(
    query: str,
    provider: str,
    hits: Sequence[SearchHit],
    *,
    max_characters: int,
) -> Rendered:
    """Fit as many hits as ``max_characters`` allows, keeping whole entries."""
    kept: List[SearchHit] = []
    length = len(_header(query, provider, 0)) + len(CITATION_REMINDER) + 8
    for hit in hits:
        block = _block(hit, len(kept) + 1)
        # Always keep the first hit: a result list of zero entries after filtering
        # by a limit the caller set would be indistinguishable from "no hits".
        if kept and length + len(block) > max_characters:
            break
        kept.append(hit)
        length += len(block) + 1

    dropped = len(hits) - len(kept)
    while True:
        content = _compose(query, provider, kept, dropped)
        if len(content) <= max_characters or len(kept) <= 1:
            return Rendered(content=content, hits=tuple(kept), dropped=dropped)
        kept.pop()
        dropped += 1


def preview_chars(max_tokens: int) -> int:
    """How much of a persisted list stays in context (same rule as ``web_fetch``)."""
    return max(MIN_PREVIEW_CHARS, min(PREVIEW_CHARS, resolve_max_tokens(max_tokens) * 3))


def _persist(text: str, directory: Optional[Path]) -> Tuple[Optional[str], Optional[str]]:
    if directory is None:
        return None, "this run has no scratch directory"
    try:
        path = persist_text(
            ensure_dir(directory),
            new_stem(PERSIST_PREFIX) + ".md",
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

    path, error = _persist(text, directory)
    if path:
        where = (
            f"The complete list is saved at {path}; read it back with read_file "
            "(the N<TAB> prefixes are line numbers)."
        )
    else:
        where = f"It could not be saved ({error}), so only this preview is available."
    headline = (
        f"The result list is larger than one tool result returns ({len(text):,} "
        f"characters, about {report.tokens:,} tokens). {where}"
    )
    return {
        "content": f"{headline}\n\n--- preview ---\n{preview(text, preview_chars(max_tokens))}",
        "content_truncated": True,
        "persisted_path": path,
        "original_tokens": report.tokens,
    }
