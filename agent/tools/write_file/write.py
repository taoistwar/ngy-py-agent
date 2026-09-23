"""Implementation of the ``write_file`` tool: guard, encode, write atomically.

The tool's promise is documented in :mod:`agent.tools.write_file` (the package
docstring); the description and schema live in
:mod:`agent.tools.write_file.description`, the error type in
:mod:`agent.tools.write_file.errors`.
"""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from agent.tools.file_access import FileAccessConfig, resolve_write_path
from agent.tools.file_bytes import DEFAULT_NEW_FILE_MODE, write_bytes_atomic
from agent.tools.file_patch import build_git_diff, build_hunks, whole_file_hunk
from agent.tools.read_ledger import ReadLedger
from agent.tools.text_encoding import (
    DEFAULT_ENCODING,
    canonical_encoding,
    decode_file_bytes,
    encode_text,
)
from agent.tools.text_lines import apply_line_ending, dominant_line_ending, split_lines
from agent.tools.write_file.errors import WriteFileError


def _display_path(path: Path, root: Optional[Path]) -> str:
    if root is None:
        return path.as_posix()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _require_text(value: Any, argument: str) -> str:
    if not isinstance(value, str):
        raise WriteFileError(
            f"'{argument}' must be a string.", reason="invalid_argument", argument=argument
        )
    return value


def _resolve_encoding(encoding: Any, display: str) -> str:
    if encoding is not None and not isinstance(encoding, str):
        raise WriteFileError(
            "'encoding' must be a string.", reason="invalid_argument", path=display
        )
    requested = (encoding or "").strip() or DEFAULT_ENCODING
    try:
        return canonical_encoding(requested)
    except LookupError:
        raise WriteFileError(
            f"Unknown encoding {requested!r}.",
            reason="unknown_encoding",
            path=display,
        ) from None


def _read_existing(path: Path, display: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise WriteFileError(
            f"Cannot read file: {exc}", reason="read_failed", file_path=display
        ) from exc


def _guard_against_blind_overwrite(
    path: Path,
    display: str,
    ledger: ReadLedger,
    stat_now: Any,
) -> None:
    """Refuse to replace a file whose current content this run has not seen."""
    recorded = ledger.lookup(path)
    if recorded is None:
        raise WriteFileError(
            "The file already exists and has not been read in full, so writing it would "
            "destroy content you have not seen. Read it first (read_file without 'limit'), "
            "or use edit_file to change just a part of it.",
            reason="read_required",
            file_path=display,
        )
    if recorded != (stat_now.st_mtime_ns, stat_now.st_size):
        raise WriteFileError(
            "The file changed on disk after it was read; read it again before overwriting it.",
            reason="file_changed",
            file_path=display,
        )


def write_file_impl(
    file_path: str,
    content: str,
    encoding: Any,
    base_dir: Optional[str],
    access_config: Optional[FileAccessConfig],
    ledger: ReadLedger,
    extra_read_roots: Sequence[Any] = (),
) -> Dict[str, Any]:
    if not isinstance(file_path, str) or not file_path.strip():
        raise WriteFileError(
            "'file_path' must be a non-empty string.",
            reason="invalid_argument",
            argument="file_path",
        )
    content = _require_text(content, "content")

    path, root = resolve_write_path(
        file_path,
        base_dir=base_dir,
        config=access_config,
        extra_read_roots=extra_read_roots,
        # The one place allowed to create the session default: a new file needs a
        # directory to live in (ADR 0007 D4).
        create_default=True,
    )
    display = _display_path(path, root)
    requested_encoding = _resolve_encoding(encoding, display)

    exists = path.exists()
    bom = b""
    original_text: Optional[str] = None
    mode: Optional[int] = DEFAULT_NEW_FILE_MODE

    if exists:
        if not path.is_file():
            raise WriteFileError(
                "Path is not a regular file (directories and special files are not supported).",
                reason="not_a_file",
                file_path=display,
            )
        stat_before = path.stat()
        _guard_against_blind_overwrite(path, display, ledger, stat_before)
        raw = _read_existing(path, display)
        decoded = decode_file_bytes(raw, requested_encoding)
        original_text = decoded.text
        bom = decoded.bom
        write_encoding = decoded.encoding
        mode = stat.S_IMODE(stat_before.st_mode)
        ending = dominant_line_ending(original_text)
        payload_text = apply_line_ending(content, ending)
    else:
        if not path.parent.is_dir():
            raise WriteFileError(
                "The parent directory does not exist; create it first (for example with "
                "code_interpreter: os.makedirs(path, exist_ok=True)).",
                reason="parent_missing",
                file_path=display,
                parent=path.parent.as_posix(),
            )
        write_encoding = requested_encoding
        ending = dominant_line_ending(content)
        payload_text = content

    payload = bom + encode_text(payload_text, write_encoding)

    if exists:
        stat_after = path.stat()
        if (stat_after.st_mtime_ns, stat_after.st_size) != (
            stat_before.st_mtime_ns,
            stat_before.st_size,
        ):
            raise WriteFileError(
                "The file changed on disk after it was read; read it again before overwriting it.",
                reason="file_changed",
                file_path=display,
            )

    try:
        write_bytes_atomic(path, payload, mode)
    except OSError as exc:
        raise WriteFileError(
            f"Cannot write file: {exc}", reason="write_failed", path=display
        ) from exc

    # This run now holds the whole content it just wrote, so a later overwrite is
    # allowed without another read.
    written = path.stat()
    ledger.record(path, written.st_mtime_ns, written.st_size)

    details: Dict[str, Any] = {
        "file_path": display,
        "encoding": write_encoding,
        "bom": bool(bom),
        "created": not exists,
        "inserted_line_ending": ending,
        "bytes_written": len(payload),
    }
    if requested_encoding != write_encoding:
        # The byte order mark outranked the argument; say so instead of hiding it.
        details["requested_encoding"] = requested_encoding

    if original_text is not None:
        details["content_changed"] = payload_text != original_text
        details["original_file"] = original_text
        old_lines = split_lines(original_text)
        new_lines = split_lines(payload_text)
        details["gitDiff"] = build_git_diff(
            display,
            build_hunks(
                [[whole_file_hunk(len(old_lines), len(new_lines))]],
                old_lines,
                new_lines,
                keep_cr=True,
            ),
        )

    return details
