"""Turning a text file into numbered lines, under a hard byte ceiling.

Only the line-oriented half of ``read_file`` lives here: streaming decoded lines,
applying the requested window, and re-emitting each line with its original ending
so that stripping the ``N<TAB>`` prefixes reproduces the file bytes exactly.
"""

import io
from pathlib import Path
from typing import Any, List, Optional, Tuple

from agent.tools.read_file.description import LINE_NUMBER_SEPARATOR
from agent.tools.read_file.errors import ReadFileError
from agent.tools.text_encoding import REASON_DECODE_FAILED, DecodeError, suggest_encodings
from agent.tools.text_lines import split_line_ending


def _iter_text_lines(path: Path, encoding: str, skip: int):
    """Stream decoded lines, splitting on ``\\r\\n`` / ``\\n`` / ``\\r`` only."""
    with open(path, "rb") as handle:
        if skip:
            handle.seek(skip)
        with io.TextIOWrapper(handle, encoding=encoding, errors="strict", newline="") as reader:
            yield from reader


def _decode_failure(
    exc: UnicodeDecodeError, encoding: str, head: bytes, display: str
) -> DecodeError:
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
