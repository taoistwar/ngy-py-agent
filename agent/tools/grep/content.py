"""The ``content`` output mode: matching lines, context lines and pagination.

Rendering follows ripgrep, because that shape is what models have read a million
times:

- a match is ``path:line:text``, a context line is ``path-line-text`` - the
  separator alone says whether the line matched, so no marker is spent on it;
- ``--`` separates groups that are not adjacent, so a gap is never mistaken for a
  contiguous block;
- without line numbers only ``path:text`` is emitted (there is nothing to number
  by, and inventing a number would be worse).

Pagination happens **while rendering**, not after: ``offset`` and ``head_limit``
count emitted lines, so a search that would answer with a hundred thousand lines
stops as soon as it has enough, instead of building them all first.

Context lines belong to line mode only. A ``multiline`` match is already a block
of source, so surrounding it with more lines would bury the part that matched.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from agent.tools.file_access import display_path
from agent.tools.grep.description import DEFAULT_HEAD_LIMIT, MAX_COLUMNS
from agent.tools.grep.regex import Matcher, MatchTimeout
from agent.tools.grep.scan import Candidate, read_text
from agent.tools.text_lines import line_index, line_offsets

# Marks a gap between two context groups, so an unrelated match is never read as
# contiguous with the one before it.
SEPARATOR = "--"


@dataclass(frozen=True)
class ContentOptions:
    """How the matching lines should be laid out."""

    offset: int = 0
    # ``None`` = no limit (``head_limit: 0``).
    limit: Optional[int] = DEFAULT_HEAD_LIMIT
    before: int = 0
    after: int = 0
    line_numbers: bool = True
    multiline: bool = False


@dataclass(frozen=True)
class ContentOutcome:
    lines: Tuple[str, ...]
    # Results the search produced, before ``offset``/``head_limit`` cut them down.
    # When the page is empty this is what tells "nothing matched" apart from
    # "the offset is past the end".
    found: int
    truncated: bool
    timed_out: bool


def collect_content(
    candidates: Sequence[Candidate],
    matcher: Matcher,
    options: ContentOptions,
    deadline: float,
    workspace: Optional[Path],
    timeouts: List[Path],
) -> ContentOutcome:
    """Render matching lines until the limit, the budget or the candidates run out.

    A file whose matching exceeds the per-call timeout is dropped and recorded in
    ``timeouts``: a partial answer must never look like a complete one.
    """
    rendered: List[str] = []
    skipped = 0
    truncated = False
    timed_out = False

    for candidate in candidates:
        if time.monotonic() >= deadline:
            timed_out = True
            break
        loaded = read_text(candidate.path)
        if loaded is None:
            continue
        text, lines = loaded
        display = display_path(candidate.path, workspace)
        try:
            block = (
                _render_multiline(display, text, matcher)
                if options.multiline
                else _render_lines(display, lines, matcher, options)
            )
        except MatchTimeout:
            timeouts.append(candidate.path)
            continue
        for line in block:
            if skipped < options.offset:
                skipped += 1
                continue
            if options.limit is not None and len(rendered) >= options.limit:
                # One line more than asked for is exactly what proves the answer
                # is incomplete, which is what ``truncated`` promises.
                truncated = True
                break
            if not rendered and line == SEPARATOR:
                # A page must not open with a group separator: it would describe
                # a gap above the first line the caller is being shown.
                continue
            rendered.append(line)
        if truncated:
            break

    return ContentOutcome(tuple(rendered), skipped + len(rendered), truncated, timed_out)


def _render_lines(
    display: str, lines: Sequence[str], matcher: Matcher, options: ContentOptions
) -> List[str]:
    """Format the matching lines of one file, with context and group separators."""
    matched = matcher.matching_lines(lines)
    if not matched:
        return []

    matched_set = set(matched)
    out: List[str] = []
    last_printed = -1
    for index in matched:
        start = max(0, index - options.before)
        end = min(len(lines) - 1, index + options.after)
        if options.before or options.after:
            if last_printed >= 0 and start > last_printed + 1:
                out.append(SEPARATOR)
        for cursor in range(max(start, last_printed + 1), end + 1):
            out.append(
                _format_line(
                    display, cursor + 1, lines[cursor], cursor in matched_set, options.line_numbers
                )
            )
        last_printed = max(last_printed, end)
    return out


def _render_multiline(display: str, text: str, matcher: Matcher) -> List[str]:
    """Format whole matches; a match may span lines, like ripgrep's ``-U`` output."""
    matches = matcher.text_matches(text)
    if not matches:
        return []
    offsets = line_offsets(text)
    return [
        f"{display}:{line_index(offsets, start) + 1}:{_clip_block(block)}"
        for start, block in matches
    ]


def _format_line(
    display: str, number: int, text: str, is_match: bool, line_numbers: bool
) -> str:
    if not line_numbers:
        return f"{display}:{_clip(text)}"
    marker = ":" if is_match else "-"
    return f"{display}{marker}{number}{marker}{_clip(text)}"


def _clip(text: str) -> str:
    """Cut one very long line, so a minified file cannot fill the answer."""
    if len(text) <= MAX_COLUMNS:
        return text
    return f"{text[:MAX_COLUMNS]}..."


def _clip_block(block: str) -> str:
    """Cut a multi-line match by columns, keeping the block readable."""
    return _clip(block.rstrip())
