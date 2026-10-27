"""The directory walk behind ``glob``: match, sort, bound.

Three decisions live here rather than in the tool:

- **Nothing is filtered out implicitly.** No ``.gitignore`` handling, no hidden
  file skipping, no VCS directory pruning: this is discovery, and a model that
  asks for ``**/*.json`` has no way to guess which names the tool decided to
  hide. The bound is the result count, not a guess about relevance.
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

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from agent.tools.file_access import AccessDenied, FileAccessConfig, enforce_policy
from agent.tools.glob.description import MAX_RESULTS, MAX_SCANNED_ENTRIES
from agent.tools.glob.pattern import GlobPattern


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
    matches, scanned, scan_truncated = _walk(root, matcher, policy, max_scanned)
    matches.sort(key=lambda item: (-item[0], item[1].as_posix()))

    truncated = scan_truncated or len(matches) > max_results
    files = tuple(path for _mtime, path in matches[:max_results])
    return SearchResult(
        files=files,
        scanned=scanned,
        truncated=truncated,
        scan_truncated=scan_truncated,
    )


def _walk(
    root: Path,
    matcher: GlobPattern,
    policy: Optional[FileAccessConfig],
    max_scanned: int,
) -> Tuple[List[Tuple[int, Path]], int, bool]:
    """Depth-first walk; returns ``(matches, scanned, stopped_early)``."""
    matches: List[Tuple[int, Path]] = []
    scanned = 0
    # Iterative instead of recursive: a deep tree must not hit the recursion limit.
    stack: List[Path] = [root]
    while stack:
        current = stack.pop()
        # Entries are consumed while the handle is open, so the scan cap also
        # bounds memory even when a single directory holds a million files.
        try:
            with os.scandir(current) as handle:
                for entry in handle:
                    scanned += 1
                    if scanned > max_scanned:
                        return matches, scanned - 1, True
                    path = Path(entry.path)
                    if not _permitted(path, policy):
                        continue
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                    except OSError:
                        # An entry that vanished mid-walk is skipped, not fatal.
                        continue
                    if is_dir:
                        stack.append(path)
                        continue
                    relative = _relative(path, root)
                    if relative is not None and matcher.matches(relative, path.name):
                        matches.append((_mtime(path), path))
        except OSError:
            # A directory the process cannot list is not an error for a search: it
            # is one silent branch of the tree, like a folder a file manager skips.
            continue
    return matches, scanned, False


def _permitted(path: Path, policy: Optional[FileAccessConfig]) -> bool:
    """Whether the global allow/deny policy lets this entry be listed.

    Pruning matters for directories: skipping a denied directory keeps the walk
    from descending into a subtree whose files must not appear in the result, so
    a name the model could never read cannot leak through a listing.
    """
    if policy is None:
        return True
    try:
        enforce_policy(path, policy, action="read")
    except AccessDenied:
        return False
    return True


def _relative(path: Path, root: Path) -> Optional[str]:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - defensive: paths come from the walk
        return None


def _mtime(path: Path) -> int:
    """Modification time in nanoseconds; unreadable entries sort last."""
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0
