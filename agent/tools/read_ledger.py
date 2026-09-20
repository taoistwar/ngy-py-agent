"""Remembers which files the current registry has read in full.

``write_file`` replaces a whole file, so it must be able to tell "the model has
seen the current content" from "the model is about to destroy something it never
looked at". Understanding cannot be verified, but two objective facts can: a full
read happened, and the bytes on disk are still the ones that were read. Those two
facts are what this ledger stores.

Scope: one ledger per ``ToolRegistry``, and a registry is built per run, so a task
cannot overwrite a file that only some other task read (see
``docs/decisions/0004-file-write-tool.md``).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

# (mtime_ns, size) captured by the last successful full read.
Fingerprint = Tuple[int, int]


class ReadLedger:
    """Path -> fingerprint of the last time this run held the whole content."""

    def __init__(self) -> None:
        self._entries: Dict[str, Fingerprint] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(path: Path) -> str:
        return os.path.normcase(str(path))

    def record(self, path: Path, mtime_ns: int, size: int) -> None:
        """Note that the whole content of ``path`` is known as of ``mtime_ns``/``size``."""
        with self._lock:
            self._entries[self._key(path)] = (int(mtime_ns), int(size))

    def lookup(self, path: Path) -> Optional[Fingerprint]:
        """Fingerprint of the last full read, or ``None`` when there was none."""
        with self._lock:
            return self._entries.get(self._key(path))

    def forget(self, path: Path) -> None:
        with self._lock:
            self._entries.pop(self._key(path), None)


# Used when a tool is built directly (tests, scripts) instead of through a
# registry; keeping one process-wide instance means read and write still pair up.
DEFAULT_LEDGER = ReadLedger()
