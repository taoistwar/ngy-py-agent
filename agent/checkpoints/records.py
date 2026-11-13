"""What the store reports back, and how git's own output becomes that.

The parsers live here because they encode one decision worth reading on its own: the
diff calls always pass ``--no-renames``, so every entry is single-path and a per-file
revert never has to guess what "R100 old -> new" means.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

STATUS_ADDED = "added"
STATUS_MODIFIED = "modified"
STATUS_DELETED = "deleted"


@dataclass(frozen=True)
class Change:
    """One file this task changed."""

    path: str
    status: str
    additions: int = 0
    deletions: int = 0
    #: The disk no longer holds what the task left behind, so undoing this file
    #: would overwrite somebody else's edit (ADR 0020 D5).
    conflict: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "status": self.status,
            "additions": self.additions,
            "deletions": self.deletions,
            "conflict": self.conflict,
        }


@dataclass
class RevertResult:
    """What a revert actually did, per file.

    A revert is not all-or-nothing: a file the user has edited since the task wrote it
    is a conflict, and refusing *that file* must not refuse the rest.
    """

    restored: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.conflicts and not self.skipped

    def to_dict(self) -> Dict[str, Any]:
        return {
            "restored": list(self.restored),
            "conflicts": list(self.conflicts),
            "skipped": list(self.skipped),
            "clean": self.clean,
        }


def status_of(code: str) -> str:
    if code == "A":
        return STATUS_ADDED
    if code == "D":
        return STATUS_DELETED
    return STATUS_MODIFIED


def parse_name_status(raw: bytes) -> List[Tuple[str, str]]:
    """Parse ``git diff --name-status -z`` into ``(status, path)`` pairs."""
    fields = [item for item in raw.split(b"\0") if item]
    pairs: List[Tuple[str, str]] = []
    for index in range(0, len(fields) - 1, 2):
        status = fields[index].decode("utf-8", "replace")[:1]
        path = fields[index + 1].decode("utf-8", "replace")
        pairs.append((status, path))
    return pairs


def parse_numstat(raw: bytes) -> Dict[str, Tuple[int, int]]:
    """Parse ``git diff --numstat -z`` into ``path -> (additions, deletions)``.

    With ``-z`` each entry is one NUL-terminated record of ``added\\tdel\\tpath``;
    binary files report ``-`` for both counts.
    """
    counts: Dict[str, Tuple[int, int]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        parts = record.decode("utf-8", "replace").split("\t")
        if len(parts) < 3:
            continue
        added, removed = parts[0], parts[1]
        # A path containing a tab survives the split; it is everything past the second.
        path = "\t".join(parts[2:])
        counts[path] = (
            0 if added == "-" else int(added or 0),
            0 if removed == "-" else int(removed or 0),
        )
    return counts
