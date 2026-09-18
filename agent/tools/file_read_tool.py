"""Workspace scoped file reading tool.

Reading is bounded on three axes so a single call can never blow up the model
context:

- the path must resolve inside the workspace root (``base_dir``),
- the raw bytes are capped (``max_size_bytes`` when reading to the end of file,
  ``min(max_size_bytes, budget * 4)`` when a line range is requested),
- the returned text must pass the three step token budget check.
"""

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from agent.tools.file_access import (
    AccessDenied,
    FileAccessConfig,
    load_access_config,
    resolve_read_path,
)
from agent.tools.token_budget import check_text, resolve_max_tokens
from agent.tools.tokenizers import MAX_BYTES_PER_TOKEN, get_token_counter

# Hard ceiling for the "read to the end of file" path.
MAX_FULL_READ_BYTES = 256 * 1024

# Bytes inspected when deciding whether a file is binary.
BINARY_SNIFF_BYTES = 8192

TEXT_ENCODING = "utf-8"

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
    "continue with a new 'offset' when needed."
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
    },
    "required": ["file_path"],
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


def _ensure_readable_file(path: Path) -> None:
    if not path.exists():
        raise ReadFileError("File not found.", path=path.as_posix())
    if not path.is_file():
        raise ReadFileError(
            "Path is not a regular file (directories and special files are not supported).",
            path=path.as_posix(),
        )
    if _looks_binary(path):
        raise ReadFileError("File looks binary; only text files can be read.", path=path.as_posix())


def _looks_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            return b"\x00" in handle.read(BINARY_SNIFF_BYTES)
    except OSError as exc:
        raise ReadFileError(f"Cannot read file: {exc}", path=path.as_posix()) from exc


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


def _read_slice(path: Path, start: int, count: int, byte_limit: int) -> Tuple[list[str], bool, int, int]:
    """Read ``count`` lines from ``start``.

    Returns ``(lines, has_more, used_bytes, scanned_lines)``.
    """
    selected: list[str] = []
    used = 0
    has_more = False
    scanned = 0
    with open(path, "r", encoding=TEXT_ENCODING, errors="replace", newline="") as handle:
        for number, raw in enumerate(handle, 1):
            scanned = number
            if number < start:
                continue
            if len(selected) >= count:
                has_more = True
                break
            used += len(raw.encode("utf-8"))
            if used > byte_limit:
                raise ReadFileError(
                    "Requested line range is too large to return in one call; narrow 'offset'/'limit' and try again.",
                    byte_limit=byte_limit,
                )
            selected.append(raw.rstrip("\r\n"))
    return selected, has_more, used, scanned


def _read_to_end(path: Path, start: int, byte_limit: int) -> Tuple[list[str], int, int]:
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
    with open(path, "r", encoding=TEXT_ENCODING, errors="replace", newline="") as handle:
        lines = [raw.rstrip("\r\n") for raw in handle]
    total_lines = len(lines)
    if start > 1:
        lines = lines[start - 1 :]
    return lines, sum(len(line.encode("utf-8")) + 1 for line in lines), total_lines


def _format_lines(lines: list[str], start: int) -> str:
    if not lines:
        return ""
    width = len(str(start + len(lines) - 1))
    return "\n".join(f"{number:>{width}}{LINE_NUMBER_SEPARATOR}{line}" for number, line in enumerate(lines, start))


def _build_result(
    display: str,
    start: int,
    lines: list[str],
    has_more: bool,
    used_bytes: int,
    total_lines: Optional[int],
    budget_report: Dict[str, Any],
    content: str,
) -> Dict[str, Any]:
    end = start + len(lines) - 1 if lines else start - 1
    return {
        "path": display,
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
    base_dir: Optional[str],
    max_tokens: int,
    provider: str,
    model: str,
    access_config: Optional[FileAccessConfig] = None,
) -> Dict[str, Any]:
    start, count = _normalize_line_range(offset, limit)
    raw_path = (file_path or "").strip()
    if not raw_path:
        raise ReadFileError("'file_path' must not be empty.")
    path, root = resolve_read_path(raw_path, base_dir=base_dir, config=access_config)
    _ensure_readable_file(path)
    display = _display_path(path, root)

    budget = resolve_max_tokens(max_tokens)
    if count is None:
        byte_limit = MAX_FULL_READ_BYTES
        lines, used_bytes, total_lines = _read_to_end(path, start, byte_limit)
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
        lines, has_more, used_bytes, scanned = _read_slice(path, start, count, byte_limit)
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

    return _build_result(display, start, lines, has_more, used_bytes, total_lines, token_check.to_dict(), content)


def make_read_file_tool(
    base_dir: Optional[str],
    max_tokens: int = 0,
    provider: str = "",
    model: str = "",
    access_config: Optional[FileAccessConfig] = None,
):
    """Bind the read tool to a workspace root and an output token budget."""
    config = access_config if access_config is not None else load_access_config()

    def read_file(file_path: str, offset: Any = 1, limit: Any = None) -> Dict[str, Any]:
        try:
            return _read_file_impl(file_path, offset, limit, base_dir, max_tokens, provider, model, config)
        except ReadFileError as exc:
            return exc.to_dict()
        except AccessDenied as exc:
            return exc.to_dict()

    return read_file
