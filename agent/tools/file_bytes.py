"""Byte-level file writing shared by the mutating file tools.

``edit_file`` and ``write_file`` both replace files through a temporary file in
the destination directory: the payload is complete before it is swapped in, so a
crash cannot leave a half-written file behind. The temporary file also carries
the destination mode, because ``os.replace`` swaps the inode and would otherwise
reset permissions (see ``docs/decisions/0003-edit-write-and-patch.md``).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

# Mode used when the file does not exist yet. A fixed default rather than the
# process umask: reading the umask means setting it, which is not thread safe and
# tasks run in threads.
DEFAULT_NEW_FILE_MODE = 0o644

TEMP_FILE_PREFIX = ".write-"
TEMP_FILE_SUFFIX = ".tmp"


def write_bytes_atomic(path: Path, payload: bytes, mode: Optional[int] = None) -> None:
    """Replace ``path`` with ``payload``, raising ``OSError`` when it fails.

    Callers map ``OSError`` onto their own error type so each tool keeps its own
    failure contract.
    """
    handle = None
    temp_name = ""
    try:
        descriptor, temp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=TEMP_FILE_PREFIX, suffix=TEMP_FILE_SUFFIX
        )
        handle = os.fdopen(descriptor, "wb")
        handle.write(payload)
        handle.close()
        handle = None
        if mode is not None:
            try:
                os.chmod(temp_name, mode)
            except OSError:  # pragma: no cover - platform specific
                pass
        os.replace(temp_name, path)
    finally:
        if handle is not None:
            handle.close()
        if temp_name and os.path.exists(temp_name):
            try:
                os.unlink(temp_name)
            except OSError:  # pragma: no cover - best effort cleanup
                pass
