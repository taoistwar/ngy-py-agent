"""The directory walk behind ``glob``: match, sort, bound.

Three decisions live here rather than in the tool:

- **Nothing is filtered out implicitly.** No ``.gitignore`` handling, no hidden
  file skipping, no VCS directory pruning: this is discovery, and a model that
  asks for ``**/*.json`` has no way to guess which names the tool decided to
  hide. The bound is the result count, not a guess about relevance. (``grep``
  makes the opposite call for contents and skips VCS directories; the walk
  itself is shared, see :mod:`agent.tools.file_walk`.)
- **Newest first.** The list is truncated, so the order decides what survives:
  a file touched minutes ago is far more likely to be the one being worked on
  than one last modified a year ago.
- **Symlinks are not followed.** A linked directory could loop forever or drag
  the walk out of the workspace; a linked *file* is still listed, because it is
  a real entry a reader can open.

The walk stops at ``max_scanned`` entries so an accidental ``**`` on a huge tree
returns quickly instead of hanging, and says so (``scan_truncated``) instead of
pretending the answer is complete.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from agent.tools.file_access import FileAccessConfig
from agent.tools.file_walk import MAX_SCANNED_ENTRIES, FileWalk, mtime_ns
from agent.tools.glob.description import MAX_RESULTS
from agent.tools.glob_pattern import GlobPattern


@dataclass(frozen=True)
class SearchResult:
    """What one walk found: the returned files plus the honesty flags."""

    files: Tuple[Path, ...]
    scanned: int
    # More files matched than were returned.
    truncated: bool
    # The walk stopped before finishing, so even ``truncated`` understates it.
    scan_truncated: bool


def search_files(
    root: Path,
    matcher: GlobPattern,
    policy: Optional[FileAccessConfig] = None,
    max_results: int = MAX_RESULTS,
    max_scanned: int = MAX_SCANNED_ENTRIES,
) -> SearchResult:
    """Return up to ``max_results`` files below ``root`` matching ``matcher``."""
    walk = FileWalk(root, policy=policy, max_scanned=max_scanned)
    matches: List[Tuple[int, Path]] = []
    for path in walk:
        relative = _relative(path, root)
        if relative is not None and matcher.matches(relative, path.name):
            matches.append((mtime_ns(path), path))

    matches.sort(key=lambda item: (-item[0], item[1].as_posix()))
    truncated = walk.stopped_early or len(matches) > max_results
    files = tuple(path for _stamp, path in matches[:max_results])
    return SearchResult(
        files=files,
        scanned=walk.scanned,
        truncated=truncated,
        scan_truncated=walk.stopped_early,
    )


def _relative(path: Path, root: Path) -> Optional[str]:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - defensive: paths come from the walk
        return None
