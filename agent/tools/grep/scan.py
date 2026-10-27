"""Everything ``grep`` does before matching: pick the files, then read them.

Two jobs, both about touching the disk, which is why they sit together:

- **Choose candidates.** The search root resolves through ``file_access`` (so a
  search is as confined as a read), the walk skips VCS metadata, the ``glob`` and
  ``type`` filters narrow it further, and credential-like files are dropped with
  the names kept aside. Candidates come back **newest first**: the output is
  truncated, so the order decides what survives, and a file touched minutes ago
  is the one most likely to be under discussion.
- **Turn one file into text.** Binary, oversized and unreadable files are
  skipped rather than reported: a search that fails on one of ten thousand files
  is not an error, it is a search. Decoding follows the file's byte order mark
  when it has one and falls back to UTF-8 with replacement otherwise - a search
  tool must not refuse to look at a file because one byte in it is odd.

Credential-like files are skipped deliberately: ``grep`` returns *contents*, and
a tool that prints the lines of ``.env`` without asking would be a way around
the confirmation ``read_file`` performs for exactly those files. The names are
reported so the model can go through ``read_file`` instead.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from agent.tools.file_access import FileAccessConfig, display_path, resolve_read_path
from agent.tools.file_walk import SEARCH_SKIP_DIRS, FileWalk, mtime_ns
from agent.tools.glob_pattern import GlobPattern
from agent.tools.grep.description import MAX_FILE_BYTES, MAX_SCANNED_FILES
from agent.tools.grep.errors import GrepError
from agent.tools.permissions import is_sensitive_path
from agent.tools.text_encoding import (
    BINARY_SNIFF_BYTES,
    DEFAULT_ENCODING,
    detect_bom,
    looks_binary,
)
from agent.tools.text_lines import split_lines, strip_line_ending


@dataclass(frozen=True)
class Candidate:
    """One file to search, with the timestamp used to rank it."""

    path: Path
    mtime: int


@dataclass(frozen=True)
class CandidateSet:
    """The files to search plus what the walk had to leave out."""

    files: Tuple[Candidate, ...]
    scanned: int
    # The walk hit its entry cap: files below it were never considered.
    scan_truncated: bool
    # The wall-clock budget ran out mid-walk.
    timed_out: bool
    skipped_sensitive: Tuple[str, ...]


def resolve_root(
    requested: Optional[str],
    base_dir: Optional[str],
    config: Optional[FileAccessConfig],
    extra_read_roots: Sequence[str],
) -> Tuple[Path, Optional[Path]]:
    """Resolve the search root; returns ``(root, workspace_root)``."""
    target = requested or "."
    root, workspace = resolve_read_path(
        target,
        base_dir=base_dir,
        config=config,
        extra_read_roots=extra_read_roots,
    )
    if not root.exists():
        raise GrepError(
            "Search path not found.",
            reason="path_not_found",
            path=display_path(root, workspace),
        )
    return root, workspace


def collect_candidates(
    root: Path,
    workspace: Optional[Path],
    matcher: Optional[GlobPattern],
    extensions: Optional[Tuple[str, ...]],
    policy: Optional[FileAccessConfig],
    deadline: float,
) -> CandidateSet:
    """Every searchable file below ``root`` (or ``root`` itself), newest first."""
    skipped: List[str] = []
    if root.is_file():
        candidate = _keep(root, root.parent, matcher, extensions, workspace, skipped)
        files = (candidate,) if candidate is not None else ()
        return CandidateSet(files, 1, False, False, tuple(skipped))

    walk = FileWalk(root, policy=policy, skip_dirs=SEARCH_SKIP_DIRS, max_scanned=MAX_SCANNED_FILES)
    candidates: List[Candidate] = []
    timed_out = False
    for path in walk:
        if time.monotonic() >= deadline:
            timed_out = True
            break
        candidate = _keep(path, root, matcher, extensions, workspace, skipped)
        if candidate is not None:
            candidates.append(candidate)

    candidates.sort(key=lambda item: (-item.mtime, item.path.as_posix()))
    return CandidateSet(
        files=tuple(candidates),
        scanned=walk.scanned,
        scan_truncated=walk.stopped_early,
        timed_out=timed_out,
        skipped_sensitive=tuple(skipped),
    )


def read_text(path: Path, max_bytes: int = MAX_FILE_BYTES) -> Optional[Tuple[str, List[str]]]:
    """Decoded text of ``path`` and its lines, or ``None`` if it is not searchable."""
    try:
        if path.stat().st_size > max_bytes:
            return None
        raw = path.read_bytes()
    except OSError:
        return None

    head = raw[:BINARY_SNIFF_BYTES]
    bom = detect_bom(head)
    if bom is not None:
        # A BOM is definitive: UTF-16 text contains NUL bytes and would otherwise
        # be rejected as binary before its encoding is ever considered.
        bom_bytes, encoding = bom
        text = raw[len(bom_bytes) :].decode(encoding, errors="replace")
    elif looks_binary(head):
        return None
    else:
        text = raw.decode(DEFAULT_ENCODING, errors="replace")
    return text, [strip_line_ending(line) for line in split_lines(text)]


def _keep(
    path: Path,
    root: Path,
    matcher: Optional[GlobPattern],
    extensions: Optional[Tuple[str, ...]],
    workspace: Optional[Path],
    skipped: List[str],
) -> Optional[Candidate]:
    """The candidate for ``path``, or ``None`` when a filter or the policy drops it."""
    if extensions is not None and path.suffix.lstrip(".").lower() not in extensions:
        return None
    if matcher is not None and not matcher.matches(_relative(path, root), path.name):
        return None
    if is_sensitive_path(path):
        skipped.append(display_path(path, workspace))
        return None
    return Candidate(path=path, mtime=mtime_ns(path))


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - defensive: paths come from the walk
        return path.name
