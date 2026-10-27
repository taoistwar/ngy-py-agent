"""The two file-level output modes: which files match, and how much each does.

Both share one rule: a file is read once and the scan stops as soon as the
requested page is full. ``files_with_matches`` therefore does not read the whole
repository to list ten paths, and ``count`` - which has nothing to stop for,
because the total is part of the answer - is the one mode that reads everything
it is given.

Counts are ordered by count, descending, then by path: the file with forty hits
is the one being asked about, and a stable tie-break keeps the answer identical
between two identical runs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Pattern, Sequence, Tuple

from agent.tools.grep.scan import Candidate, read_text


@dataclass(frozen=True)
class FilesOutcome:
    files: Tuple[Path, ...]
    # Files found before ``offset``/``head_limit`` narrowed the list.
    found: int
    truncated: bool
    timed_out: bool


@dataclass(frozen=True)
class CountOutcome:
    counts: Tuple[Tuple[Path, int], ...]
    # Matching lines across every file that matched, not just the returned page.
    total: int
    found: int
    truncated: bool
    timed_out: bool


def collect_files(
    candidates: Sequence[Candidate],
    regex: Pattern[str],
    offset: int,
    limit: Optional[int],
    deadline: float,
    multiline: bool,
) -> FilesOutcome:
    """Paths of the files containing a match, newest first (the candidates are)."""
    selected: List[Path] = []
    want_last = None if limit is None else offset + limit
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
        if not _has_match(text, lines, regex, multiline):
            continue
        selected.append(candidate.path)
        if want_last is not None and len(selected) > want_last:
            truncated = True
            break

    end = len(selected) if limit is None else offset + limit
    return FilesOutcome(tuple(selected[offset:end]), len(selected), truncated, timed_out)


def collect_counts(
    candidates: Sequence[Candidate],
    regex: Pattern[str],
    offset: int,
    limit: Optional[int],
    deadline: float,
    multiline: bool,
) -> CountOutcome:
    """Matching lines per file (``multiline``: per match), most matches first."""
    counts: List[Tuple[Path, int]] = []
    timed_out = False

    for candidate in candidates:
        if time.monotonic() >= deadline:
            timed_out = True
            break
        loaded = read_text(candidate.path)
        if loaded is None:
            continue
        text, lines = loaded
        count = _count(text, lines, regex, multiline)
        if count:
            counts.append((candidate.path, count))

    counts.sort(key=lambda item: (-item[1], item[0].as_posix()))
    total = sum(count for _path, count in counts)
    end = len(counts) if limit is None else offset + limit
    return CountOutcome(
        tuple(counts[offset:end]),
        total,
        len(counts),
        end < len(counts),
        timed_out,
    )


def _has_match(text: str, lines: Sequence[str], regex: Pattern[str], multiline: bool) -> bool:
    if multiline:
        return regex.search(text) is not None
    return any(regex.search(line) is not None for line in lines)


def _count(text: str, lines: Sequence[str], regex: Pattern[str], multiline: bool) -> int:
    if multiline:
        # A block match covers several lines; the empty ones match nothing.
        return sum(1 for match in regex.finditer(text) if match.start() != match.end())
    return sum(1 for line in lines if regex.search(line) is not None)
