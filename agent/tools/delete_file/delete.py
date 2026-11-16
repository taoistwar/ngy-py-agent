"""Implementation of the ``delete_file`` tool: guard, then one unlink.

The tool's promise is documented in :mod:`agent.tools.delete_file` (the package
docstring); the description and schema live in
:mod:`agent.tools.delete_file.description`, the error type in
:mod:`agent.tools.delete_file.errors`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from agent.tools.delete_file.errors import DeleteFileError
from agent.tools.file_access import FileAccessConfig, display_path, resolve_write_path
from agent.tools.file_limits import MAX_FULL_READ_BYTES
from agent.tools.read_ledger import ReadLedger


def _verify_content_seen(
    path: Path,
    display: str,
    ledger: ReadLedger,
    mtime_ns: int,
    size: int,
) -> bool:
    """Whether this run holds the whole content that is about to be destroyed.

    Returns ``False`` only for a file the reader refuses to read as a whole: asking
    the model to read it would be asking for something impossible (ADR 0026).
    """
    if size == 0:
        # An empty file has no content to lose; its size is the whole truth about it.
        return True
    if size > MAX_FULL_READ_BYTES:
        return False

    recorded = ledger.lookup(path)
    if recorded is None:
        raise DeleteFileError(
            "The file has not been read in full in this task, so deleting it would destroy "
            "content you have not seen. Read it first (read_file without 'limit'), then "
            "delete it.",
            reason="read_required",
            file_path=display,
        )
    if recorded != (mtime_ns, size):
        raise DeleteFileError(
            "The file changed on disk after it was read; read it again before deleting it.",
            reason="file_changed",
            file_path=display,
        )
    return True


def delete_file_impl(
    file_path: str,
    base_dir: Optional[str],
    access_config: Optional[FileAccessConfig],
    ledger: ReadLedger,
    extra_read_roots: Sequence[Any] = (),
) -> Dict[str, Any]:
    if not isinstance(file_path, str) or not file_path.strip():
        raise DeleteFileError(
            "'file_path' must be a non-empty string.",
            reason="invalid_argument",
            argument="file_path",
        )

    # Resolved as a write: deletion is a modification of the workspace, so it has to
    # hit the same ceiling, the same deny rules and the same read-only roots.
    path, root = resolve_write_path(
        file_path,
        base_dir=base_dir,
        config=access_config,
        extra_read_roots=extra_read_roots,
    )
    display = display_path(path, root)

    try:
        stat_before = path.stat()
    except FileNotFoundError:
        raise DeleteFileError(
            "The file does not exist. Use glob to locate it, or check the path.",
            reason="not_found",
            file_path=display,
        ) from None
    except OSError as exc:
        raise DeleteFileError(
            f"Cannot inspect the file: {exc}", reason="stat_failed", file_path=display
        ) from exc

    if not path.is_file():
        raise DeleteFileError(
            "Path is not a regular file; delete_file removes one file and refuses "
            "directories. Remove a tree with code_interpreter (for example "
            "shutil.rmtree(path, ignore_errors=True)).",
            reason="not_a_file",
            file_path=display,
        )

    content_verified = _verify_content_seen(
        path, display, ledger, stat_before.st_mtime_ns, stat_before.st_size
    )

    try:
        path.unlink()
    except FileNotFoundError:
        # Another task (or the user) removed it between the stat and the unlink.
        raise DeleteFileError(
            "The file was already gone when the delete ran.",
            reason="not_found",
            file_path=display,
        ) from None
    except OSError as exc:
        raise DeleteFileError(
            f"Cannot delete file: {exc}", reason="delete_failed", file_path=display
        ) from exc

    # The fingerprint described a file that no longer exists. Keeping it would let a
    # file re-created at the same path be deleted without ever being read.
    ledger.forget(path)

    return {
        "file_path": display,
        "file_bytes": stat_before.st_size,
        "content_verified": content_verified,
    }
