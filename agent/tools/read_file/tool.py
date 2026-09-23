"""Implementation of the ``read_file`` tool: resolve, check, read, report.

The tool's promise is documented in :mod:`agent.tools.read_file` (the package
docstring), the description and schema in
:mod:`agent.tools.read_file.description`, the line handling in
:mod:`agent.tools.read_file.lines`, and the error type in
:mod:`agent.tools.read_file.errors`.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agent.tools.file_access import (
    AccessDenied,
    FileAccessConfig,
    load_access_config,
    resolve_read_path,
)
from agent.tools.read_file.description import MAX_FULL_READ_BYTES
from agent.tools.read_file.errors import ReadFileError
from agent.tools.read_file.lines import (
    _format_lines,
    _normalize_line_range,
    _read_slice,
    _read_to_end,
)
from agent.tools.read_ledger import DEFAULT_LEDGER, ReadLedger
from agent.tools.text_encoding import (
    BINARY_SNIFF_BYTES,
    DEFAULT_ENCODING,
    DecodeError,
    canonical_encoding,
    detect_bom,
    looks_binary,
    suggest_encodings,
)
from agent.tools.token_budget import check_text, resolve_max_tokens
from agent.tools.tokenizers import MAX_BYTES_PER_TOKEN, get_token_counter

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
