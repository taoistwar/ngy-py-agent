"""Depth-first file walk shared by the discovery tools (``glob`` and ``grep``).

Both tools need the same three guarantees, and they must not drift apart - a
search that can read one directory more than a listing is a hole nobody will
notice until it leaks:

- **Confined**: the walk never follows a directory symlink, so it cannot loop and
  cannot step out of ``root``; entries the global ``file_access`` policy denies
  are pruned instead of being read and then rejected.
- **Bounded**: it stops after ``max_scanned`` entries, so an accidental ``**``
  over a huge tree returns quickly instead of hanging the tool call.
- **Honest**: when it stops early it says so (``stopped_early``) rather than
  presenting a partial answer as a complete one.

What is deliberately *not* shared is what to do with each file: ``glob`` matches
names and sorts, ``grep`` reads contents and stops at an output limit. Callers
iterate and decide.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, Optional, Sequence

from agent.tools.file_access import FileAccessConfig, is_permitted

# Version control metadata is never interesting to search: it is machine state,
# it is large, and its contents are mostly binary or one enormous line.
VCS_DIRS = (".git", ".svn", ".hg", ".bzr", ".jj", ".sl")

# Installed dependencies and build output. These are not project source, they are
# what a search must not spend its budget on: a JS project's ``node_modules`` is
# tens of thousands of files that bury every real hit (and made a root-level
# search hit its wall-clock budget before it found anything useful in this very
# repository). Skipping is by directory *name* during the walk, so pointing
# ``path`` at one of these still searches it - an explicit request wins.
GENERATED_DIRS = (
    "node_modules",
    "bower_components",
    "jspm_packages",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".next",
    ".nuxt",
    "dist",
    "build",
    "target",
)

# What a content search skips; a listing (``glob``) skips nothing.
SEARCH_SKIP_DIRS = VCS_DIRS + GENERATED_DIRS

# Default ceiling on entries examined by one walk.
MAX_SCANNED_ENTRIES = 50_000


def mtime_ns(path: Path) -> int:
    """Modification time in nanoseconds; unreadable entries sort last (``0``)."""
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


class FileWalk:
    """Regular files below ``root``, depth-first, policy pruned and count bounded.

    Iterate it once: :attr:`scanned` and :attr:`stopped_early` describe the
    iteration that just finished (a ``break`` leaves them as they were, so a
    caller that stops on its own account must not read them as "complete").
    """

    def __init__(
        self,
        root: Path,
        policy: Optional[FileAccessConfig] = None,
        max_scanned: int = MAX_SCANNED_ENTRIES,
        skip_dirs: Sequence[str] = (),
    ) -> None:
        self.root = root
        self.policy = policy
        self.max_scanned = max_scanned
        self.skip_dirs = frozenset(skip_dirs or ())
        self.scanned = 0
        self.stopped_early = False

    def __iter__(self) -> Iterator[Path]:
        self.scanned = 0
        self.stopped_early = False
        # Iterative instead of recursive: a deep tree must not hit the recursion
        # limit. Entries are consumed while the handle is open, so the cap also
        # bounds memory when one directory holds a million files.
        stack = [self.root]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as handle:
                    for entry in handle:
                        if self._count():
                            return
                        path = Path(entry.path)
                        if not is_permitted(path, self.policy):
                            continue
                        try:
                            is_dir = entry.is_dir(follow_symlinks=False)
                        except OSError:
                            # An entry that vanished mid-walk is skipped, not fatal.
                            continue
                        if is_dir:
                            if path.name not in self.skip_dirs:
                                stack.append(path)
                            continue
                        yield path
            except OSError:
                # A directory the process cannot list is one silent branch of the
                # tree, like a folder a file manager skips.
                continue

    def _count(self) -> bool:
        """Count one examined entry; ``True`` when the cap has been reached."""
        if self.scanned >= self.max_scanned:
            self.stopped_early = True
            return True
        self.scanned += 1
        return False
