"""Workspace scoped file reading tool.

Reading is bounded on four axes so a single call can never blow up the model
context:

- the path must resolve inside the workspace root (``base_dir``),
- only text files are readable (a BOM is recognised as text; otherwise NUL bytes
  in the head mean binary),
- the raw bytes are capped (``max_size_bytes`` when reading to the end of file,
  ``min(max_size_bytes, budget * 4)`` when a line range is requested),
- the returned text must pass the three step token budget check.

The encoding is **never guessed silently**: decoding uses ``encoding`` (default
UTF-8) or the byte order mark when the file has one, and a failure is reported
with the candidate encodings that would decode the bytes so the model can retry
(see ``docs/decisions/0002-file-encoding.md``).

Line endings are deliberately **preserved** (``\\r\\n`` / ``\\n`` / ``\\r``) instead
of being normalized to ``\\n``: stripping the ``N<TAB>`` prefixes from the output
must reproduce the file bytes exactly, otherwise ``edit_file``'s strict byte
matching could never succeed on CRLF files (see
``docs/decisions/0001-file-edit-tool.md``).
"""

import io
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agent.tools.file_access import (
    AccessDenied,
    FileAccessConfig,
    load_access_config,
    resolve_read_path,
)
from agent.tools.read_ledger import DEFAULT_LEDGER, ReadLedger
from agent.tools.text_encoding import (
    BINARY_SNIFF_BYTES,
    DEFAULT_ENCODING,
    REASON_DECODE_FAILED,
    DecodeError,
    canonical_encoding,
    detect_bom,
    looks_binary,
    suggest_encodings,
)
from agent.tools.text_lines import split_line_ending
from agent.tools.token_budget import check_text, resolve_max_tokens
from agent.tools.tokenizers import MAX_BYTES_PER_TOKEN, get_token_counter

# Hard ceiling for the "read to the end of file" path.
MAX_FULL_READ_BYTES = 256 * 1024

# Line numbers are always emitted and deliberately have no opt-out switch: the
# model cannot see the real line numbers, so a numberless read turns every later
# "change line N" reference into guesswork. Saving tokens is not worth that.
LINE_NUMBER_SEPARATOR = "\t"

READ_FILE_DESCRIPTION = (
    "Read a text file. Paths are resolved against the workspace root when the session "
    "has one and can never escape it; a global allow/deny policy always applies on top. "
    "Returns the requested line range, each line prefixed with its 1-based line number "
    "followed by a single tab. Omit 'limit' to "
    "read from 'offset' to the end of the file (rejected when the file is larger than "
    "256KB). Provide 'limit' to read a specific number of lines; the returned text is "
    "rejected when it exceeds the output token budget, so prefer small ranges and "
    "continue with a new 'offset' when needed. Decoding uses 'encoding' (default UTF-8) "
    "or the file's byte order mark when it has one; when the bytes cannot be decoded you "
    "get an error listing candidate encodings, so retry with the right 'encoding'. The "
    "result reports the 'encoding' that worked - pass the same value to edit_file. "
    "Original line endings are preserved, so "
    "the text with the 'N<TAB>' prefixes stripped can be passed verbatim to edit_file "
    "as 'old_string'."
)

READ_FILE_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": (
                "Path to the file, relative to the workspace root (absolute paths are "
                "accepted only when they stay inside the workspace)."
            ),
        },
        "offset": {
            "type": "integer",
            "minimum": 0,
            "description": ("1-based line number to start from. Defaults to 1; 0 is treated as 1."),
        },
        "limit": {
            "type": "integer",
            "minimum": 0,
            "description": (
                "Number of lines to read. Omit it (or pass 0) to read from 'offset' to the end of the file."
            ),
        },
        "encoding": {
            "type": "string",
            "description": (
                "Text encoding used to decode the file (required). Use UTF-8 unless you have "
                "a reason not to. A byte order mark always wins over this value. When "
                "decoding fails the error lists candidate encodings; retry with the one "
                "that fits."
            ),
        },
    },
    "required": ["file_path", "encoding"],
}


class ReadFileError(Exception):
    """Raised when a read request cannot be served."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, **self.details}


def _display_path(path: Path, root: Optional[Path]) -> str:
    if root is None:
        return path.as_posix()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _clean_file_path(file_path: Any) -> str:
    """Validate ``file_path`` without silently rewriting it.

    The path is *not* stripped: a name with leading or trailing spaces is a real
    file name and trimming it would make that file unreachable (and the "not
    found" error misleading).
    """
    if not isinstance(file_path, str):
        raise ReadFileError("'file_path' must be a string.", reason="invalid_argument", argument="file_path")
    if not file_path.strip():
        raise ReadFileError("'file_path' must not be empty.", reason="invalid_argument", argument="file_path")
    return file_path


def _read_head(path: Path) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read(BINARY_SNIFF_BYTES)
    except OSError as exc:
        raise ReadFileError(f"Cannot read file: {exc}", path=path.as_posix()) from exc


def _ensure_text_file(path: Path, display: str, raw_path: str) -> bytes:
    """Check the path is a regular text file and return its head bytes."""
    if not path.exists():
        details: Dict[str, Any] = {"reason": "file_not_found", "path": display}
        if raw_path != raw_path.strip():
            details["hint"] = (
                f"The path carries surrounding whitespace; retry with {raw_path.strip()!r}."
            )
        raise ReadFileError("File not found.", **details)
    if not path.is_file():
        raise ReadFileError(
            "Path is not a regular file (directories and special files are not supported).",
            reason="not_a_file",
            path=display,
        )

    head = _read_head(path)
    # The BOM check must come first: UTF-16/UTF-32 text always contains NUL bytes
    # and would otherwise be rejected as binary before its encoding is considered.
    if detect_bom(head) is None and looks_binary(head):
        raise ReadFileError(
            "File looks binary; only text files can be read.", reason="binary_file", path=display
        )
    return head


def _resolve_encoding(head: bytes, encoding: Any, display: str) -> Tuple[str, int]:
    """Return ``(encoding, bom_length)``; a byte order mark outranks the argument."""
    bom_hit = detect_bom(head)
    if bom_hit is not None:
        bom_bytes, bom_encoding = bom_hit
        return bom_encoding, len(bom_bytes)

    if encoding is not None and not isinstance(encoding, str):
        raise ReadFileError(
            "'encoding' must be a string.", reason="invalid_argument", path=display
        )
    requested = (encoding or "").strip() or DEFAULT_ENCODING
    try:
        return canonical_encoding(requested), 0
    except LookupError:
        raise ReadFileError(
            f"Unknown encoding {requested!r}.",
            reason="unknown_encoding",
            path=display,
            suggested_encodings=suggest_encodings(head),
        ) from None


def _iter_text_lines(path: Path, encoding: str, skip: int):
    """Stream decoded lines, splitting on ``\\r\\n`` / ``\\n`` / ``\\r`` only."""
    with open(path, "rb") as handle:
        if skip:
            handle.seek(skip)
        with io.TextIOWrapper(handle, encoding=encoding, errors="strict", newline="") as reader:
            yield from reader


def _decode_failure(exc: UnicodeDecodeError, encoding: str, head: bytes, display: str) -> DecodeError:
    return DecodeError(
        f"Cannot decode the file as {encoding}; retry with the correct 'encoding'.",
        reason=REASON_DECODE_FAILED,
        path=display,
        encoding=encoding,
        byte_offset=exc.start,
        suggested_encodings=suggest_encodings(head),
    )


def _normalize_line_range(offset: Any, limit: Any) -> Tuple[int, Optional[int]]:
    try:
        start = int(offset) if offset is not None else 1
    except (TypeError, ValueError):
        raise ReadFileError("'offset' must be an integer.") from None
    try:
        count = int(limit) if limit is not None else None
    except (TypeError, ValueError):
        raise ReadFileError("'limit' must be an integer.") from None
    start = max(start, 1)
    if count is not None and count <= 0:
        count = None
    return start, count


def _read_slice(
    path: Path,
    encoding: str,
    skip: int,
    start: int,
    count: int,
    byte_limit: int,
    head: bytes,
    display: str,
) -> Tuple[List[str], bool, int, int]:
    """Read ``count`` lines from ``start``.

    Returns ``(lines, has_more, used_bytes, scanned_lines)``. Each entry in
    ``lines`` keeps its original line ending.
    """
    selected: List[str] = []
    used = 0
    has_more = False
    scanned = 0
    try:
        for number, raw in enumerate(_iter_text_lines(path, encoding, skip), 1):
            scanned = number
            if number < start:
                continue
            if len(selected) >= count:
                has_more = True
                break
            used += len(raw.encode(encoding))
            if used > byte_limit:
                raise ReadFileError(
                    "Requested line range is too large to return in one call; narrow 'offset'/'limit' and try again.",
                    byte_limit=byte_limit,
                )
            selected.append(raw)
    except UnicodeDecodeError as exc:
        raise _decode_failure(exc, encoding, head, display) from exc
    return selected, has_more, used, scanned


def _read_to_end(
    path: Path,
    encoding: str,
    skip: int,
    start: int,
    byte_limit: int,
    head: bytes,
    display: str,
) -> Tuple[List[str], int, int]:
    """Read from ``start`` to the end of file, rejecting oversized files upfront."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ReadFileError(f"Cannot stat file: {exc}", path=path.as_posix()) from exc
    if size > byte_limit:
        raise ReadFileError(
            "File is too large to read as a whole; request an explicit 'limit' or a narrower 'offset'.",
            file_bytes=size,
            byte_limit=byte_limit,
        )
    try:
        lines = list(_iter_text_lines(path, encoding, skip))
    except UnicodeDecodeError as exc:
        raise _decode_failure(exc, encoding, head, display) from exc
    total_lines = len(lines)
    if start > 1:
        lines = lines[start - 1 :]
    return lines, sum(len(line.encode(encoding)) for line in lines), total_lines


def _format_lines(lines: List[str], start: int) -> str:
    """Number every line while keeping its original line ending intact.

    The prefix is ``N<TAB>``; the ending is re-emitted verbatim. Stripping the
    prefixes from the returned text therefore reproduces the file bytes exactly,
    which is what lets ``edit_file`` do strict byte matching (see ADR 0001).
    """
    if not lines:
        return ""
    width = len(str(start + len(lines) - 1))
    parts = []
    for number, raw in enumerate(lines, start):
        content, ending = split_line_ending(raw)
        parts.append(f"{number:>{width}}{LINE_NUMBER_SEPARATOR}{content}{ending}")
    return "".join(parts)


def _build_result(
    display: str,
    start: int,
    lines: List[str],
    has_more: bool,
    used_bytes: int,
    total_lines: Optional[int],
    budget_report: Dict[str, Any],
    content: str,
    encoding: str,
    has_bom: bool,
) -> Dict[str, Any]:
    end = start + len(lines) - 1 if lines else start - 1
    return {
        "path": display,
        "encoding": encoding,
        "bom": has_bom,
        "start_line": start,
        "end_line": max(end, start),
        "returned_lines": len(lines),
        "total_lines": total_lines,
        "truncated": has_more,
        "file_bytes_read": used_bytes,
        "token_budget": budget_report,
        "content": content,
    }


def _read_file_impl(
    file_path: str,
    offset: Any,
    limit: Any,
    encoding: Any,
    base_dir: Optional[str],
    max_tokens: int,
    provider: str,
    model: str,
    access_config: Optional[FileAccessConfig] = None,
    ledger: Optional[ReadLedger] = None,
    extra_read_roots: Sequence[Any] = (),
) -> Dict[str, Any]:
    start, count = _normalize_line_range(offset, limit)
    raw_path = _clean_file_path(file_path)
    path, root = resolve_read_path(
        raw_path, base_dir=base_dir, config=access_config, extra_read_roots=extra_read_roots
    )
    display = _display_path(path, root)
    head = _ensure_text_file(path, display, raw_path)
    effective, skip = _resolve_encoding(head, encoding, display)
    try:
        stat_before = path.stat()
    except OSError as exc:
        raise ReadFileError(f"Cannot stat file: {exc}", path=display) from exc

    budget = resolve_max_tokens(max_tokens)
    if count is None:
        byte_limit = MAX_FULL_READ_BYTES
        lines, used_bytes, total_lines = _read_to_end(
            path, effective, skip, start, byte_limit, head, display
        )
        has_more = False
        if not lines and start > max(total_lines, 1):
            raise ReadFileError(
                "Requested 'offset' is past the end of the file.",
                offset=start,
                total_lines=total_lines,
                path=display,
            )
    else:
        byte_limit = min(MAX_FULL_READ_BYTES, budget * MAX_BYTES_PER_TOKEN)
        lines, has_more, used_bytes, scanned = _read_slice(
            path, effective, skip, start, count, byte_limit, head, display
        )
        total_lines = None if has_more else scanned
        if not lines and start > scanned:
            raise ReadFileError(
                "Requested 'offset' is past the end of the file.",
                offset=start,
                total_lines=scanned,
                path=display,
            )

    content = _format_lines(lines, start)
    token_check = check_text(
        content,
        budget,
        provider=provider,
        model=model,
        counter=get_token_counter(provider, model),
    )
    if not token_check.ok:
        raise ReadFileError(
            "Requested line range exceeds the output token budget; narrow 'offset'/'limit'.",
            path=display,
            **token_check.to_dict(),
        )

    if count is None and start == 1 and ledger is not None:
        # Reading the whole file from line 1 is the precondition write_file checks
        # before it may replace the file, so record it with the bytes it came from.
        ledger.record(path, stat_before.st_mtime_ns, stat_before.st_size)

    return _build_result(
        display,
        start,
        lines,
        has_more,
        used_bytes,
        total_lines,
        token_check.to_dict(),
        content,
        effective,
        bool(skip),
    )


def make_read_file_tool(
    base_dir: Optional[str],
    max_tokens: int = 0,
    provider: str = "",
    model: str = "",
    access_config: Optional[FileAccessConfig] = None,
    ledger: Optional[ReadLedger] = None,
    extra_read_roots: Sequence[Any] = (),
):
    """Bind the read tool to a workspace root and an output token budget."""
    config = access_config if access_config is not None else load_access_config()
    read_ledger = ledger if ledger is not None else DEFAULT_LEDGER

    def read_file(
        file_path: str,
        offset: Any = 1,
        limit: Any = None,
        encoding: Any = None,
    ) -> Dict[str, Any]:
        try:
            return _read_file_impl(
                file_path,
                offset,
                limit,
                encoding,
                base_dir,
                max_tokens,
                provider,
                model,
                config,
                read_ledger,
                extra_read_roots,
            )
        except ReadFileError as exc:
            return exc.to_dict()
        except DecodeError as exc:
            return exc.to_dict()
        except AccessDenied as exc:
            return exc.to_dict()

    return read_file
