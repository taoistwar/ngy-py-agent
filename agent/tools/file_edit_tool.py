"""Workspace scoped file editing tool: exact-string replacement.

The match is **strict byte-for-byte at the text level**: ``old_string`` must
appear in the file exactly as provided, with no newline or whitespace
normalization. That contract is only usable because ``read_file`` preserves the
original line endings, so the text the model reconstructs from a read is
byte-identical to the file (see ``docs/decisions/0001-file-edit-tool.md``).

The **write** is done at the byte level: only the matched byte range is replaced,
everything else is copied verbatim. Decoding the whole file, replacing and
re-encoding it would rewrite bytes the edit never touched on encodings whose
decode/encode pair is not a bijection (``cp932`` has hundreds of such byte
pairs, verified by ``test/tools/file_edit_tool_test.py``), so the splice keeps
untouched bytes pristine on every encoding (see
``docs/decisions/0002-file-encoding.md``).

A single call produces two outputs:

- the **model** only sees a one line success summary (or a readable error), and
- the **UI / external consumers** receive ``original_file``, ``structured_patch``
  and ``gitDiff`` through a dedicated ``file_edit`` event, never through the
  model's context.

The tool cannot create files: ``old_string`` must already exist.
"""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agent.models import EventCategory, ToolOutcome
from agent.tools.file_access import (
    AccessDenied,
    FileAccessConfig,
    load_access_config,
    resolve_write_path,
)
from agent.tools.file_bytes import write_bytes_atomic
from agent.tools.file_patch import CONTEXT_LINES, build_git_diff, build_hunks
from agent.tools.read_ledger import DEFAULT_LEDGER, ReadLedger
from agent.tools.text_encoding import (
    DecodeError,
    EncodeError,
    decode_file_bytes,
    encode_text,
)
from agent.tools.text_lines import (
    apply_line_ending,
    dominant_line_ending,
    line_index,
    offsets_from_lines,
    split_lines,
)

EDIT_FILE_DESCRIPTION = (
    "Replace an exact string inside a text file. Paths resolve against the workspace root "
    "and can never escape it; the global allow/deny policy applies on top. "
    "'old_string' is matched BYTE FOR BYTE, so it must appear exactly as in the file, "
    "line endings included: strip the 'N<TAB>' prefix from read_file output and reuse the "
    "text verbatim. The match must be unique - when 'old_string' occurs more than once the "
    "call is rejected and you must add surrounding context, or pass replace_all=true to "
    "replace every occurrence. Decoding uses 'encoding' (default UTF-8) or the file's byte "
    "order mark when it has one; when the bytes cannot be decoded you get an error listing "
    "candidate encodings, so retry with the right 'encoding'. Inserted text is rewritten to "
    "the line ending the file already uses, and the byte order mark is preserved; only the "
    "matched range is rewritten, so untouched bytes are never touched. Edits are written "
    "atomically, and the file's permissions are carried over."
)

EDIT_FILE_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Path to the file, relative to the workspace root.",
        },
        "old_string": {
            "type": "string",
            "description": (
                "Exact text to replace. Must be unique unless 'replace_all' is true."
            ),
        },
        "new_string": {
            "type": "string",
            "description": "Replacement text. An empty string deletes the matched text.",
        },
        "replace_all": {
            "type": "boolean",
            "description": (
                "Replace every occurrence instead of requiring a unique match. Defaults to false."
            ),
        },
        "encoding": {
            "type": "string",
            "description": (
                "Text encoding used to decode and re-encode the file. Defaults to UTF-8. "
                "Use the 'encoding' value reported by read_file. A byte order mark always "
                "wins over this value."
            ),
        },
    },
    "required": ["file_path", "old_string", "new_string", "encoding"],
}


class EditFileError(Exception):
    """Raised when an edit request cannot be served."""

    def __init__(self, message: str, reason: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, "reason": self.reason, **self.details}


def _display_path(path: Path, root: Optional[Path]) -> str:
    if root is None:
        return path.as_posix()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _require_text(value: Any, argument: str) -> str:
    """Reject non-string arguments instead of letting them raise ``TypeError``."""
    if not isinstance(value, str):
        raise EditFileError(
            f"'{argument}' must be a string.", reason="invalid_argument", argument=argument
        )
    return value


def _read_bytes(path: Path, display: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise EditFileError(
            f"Cannot read file: {exc}", reason="read_failed", file_path=display
        ) from exc


def _match_spans(text: str, old_string: str, replace_all: bool) -> List[int]:
    """Character offsets of every (non-overlapping) match."""
    spans: List[int] = []
    cursor = text.find(old_string)
    while cursor != -1:
        spans.append(cursor)
        if not replace_all:
            break
        cursor = text.find(old_string, cursor + len(old_string))
    return spans


def _replace_spans(text: str, spans: List[int], old_string: str, new_string: str) -> str:
    parts: List[str] = []
    cursor = 0
    for start in spans:
        parts.append(text[cursor:start])
        parts.append(new_string)
        cursor = start + len(old_string)
    parts.append(text[cursor:])
    return "".join(parts)


def _splice_bytes(
    raw: bytes,
    text: str,
    bom: bytes,
    encoding: str,
    spans: List[int],
    old_string: str,
    inserted: str,
    display: str,
) -> bytes:
    """Replace only the matched byte ranges, copying every other byte verbatim."""
    body = raw[len(bom) :]
    old_bytes = encode_text(old_string, encoding)
    new_bytes = encode_text(inserted, encoding)

    parts: List[bytes] = []
    byte_cursor = 0
    char_cursor = 0
    for start in spans:
        byte_start = byte_cursor + len(encode_text(text[char_cursor:start], encoding))
        byte_end = byte_start + len(old_bytes)
        if body[byte_start:byte_end] != old_bytes:
            raise EditFileError(
                "The bytes behind 'old_string' do not match a canonical "
                f"{encoding} sequence, so this edit cannot be applied byte-for-byte. "
                "Rewrite the file as UTF-8 first.",
                reason="encoding_mismatch",
                file_path=display,
                encoding=encoding,
            )
        parts.append(body[byte_cursor:byte_start])
        parts.append(new_bytes)
        byte_cursor = byte_end
        char_cursor = start + len(old_string)
    parts.append(body[byte_cursor:])
    return bom + b"".join(parts)


def _line_span(offsets: List[int], start: int, end: int) -> Tuple[int, int]:
    """Inclusive line range covering ``[start, end)``; empty when ``end <= start``."""
    if not offsets:
        return 0, -1
    first = line_index(offsets, start)
    if end <= start:
        return first, first - 1
    return first, max(line_index(offsets, end - 1), first)


def _collapsed_groups(
    spans: List[int],
    old_length: int,
    inserted_length: int,
    old_offsets: List[int],
    new_offsets: List[int],
) -> List[Dict[str, int]]:
    """One item per group of matches that covers distinct whole lines.

    Matches landing on the same line are collapsed into a single whole-line
    replacement, because the diff reports whole lines: the surrounding text on
    that line changed too, even when the match itself was a fragment.
    """
    groups: List[Dict[str, int]] = []
    for index, start in enumerate(spans):
        delta = index * (inserted_length - old_length)
        o_first, o_last = _line_span(old_offsets, start, start + old_length)
        n_first, n_last = _line_span(new_offsets, start + delta, start + delta + inserted_length)

        if groups and o_first <= groups[-1]["old_last"]:
            last = groups[-1]
            last["old_last"] = max(last["old_last"], o_last)
            last["new_first"] = min(last["new_first"], n_first)
            last["new_last"] = max(last["new_last"], n_last)
            continue

        groups.append(
            {
                "old_first": o_first,
                "old_last": o_last,
                "new_first": n_first,
                "new_last": n_last,
            }
        )
    return groups


def _merge_by_context(items: List[Dict[str, int]], last_line: int) -> List[List[Dict[str, int]]]:
    """Merge items whose context windows touch, so ``gitDiff`` stays applicable."""
    merged: List[List[Dict[str, int]]] = []
    current: List[Dict[str, int]] = []
    group_end = 0

    for item in items:
        start = max(item["old_first"] - CONTEXT_LINES, 0)
        end = min(item["old_last"] + CONTEXT_LINES, last_line)
        if current and start <= group_end + 1:
            current.append(item)
            group_end = max(group_end, end)
            continue
        if current:
            merged.append(current)
        current = [item]
        group_end = end

    if current:
        merged.append(current)
    return merged


@dataclass(frozen=True)
class _PreparedEdit:
    """Everything an edit needs, computed **without touching the file on disk**.

    ``edit_file`` writes this; the confirmation dialog asks for it so it can show
    the diff before the user decides (ADR 0006 D11). That is only possible because
    reading, matching and byte-splicing are all side-effect free.
    """

    path: Path
    display: str
    before: Any
    decoded: Any
    spans: List[int]
    ending: str
    updated_text: str
    updated_raw: bytes
    old_lines: List[str]
    new_lines: List[str]
    groups: List[Dict[str, int]]


def _prepare_edit(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool,
    encoding: Optional[str],
    base_dir: Optional[str],
    access_config: Optional[FileAccessConfig],
    extra_read_roots: Sequence[Any] = (),
) -> _PreparedEdit:
    if not isinstance(file_path, str) or not file_path.strip():
        raise EditFileError(
            "'file_path' must be a non-empty string.", reason="invalid_argument", argument="file_path"
        )
    old_string = _require_text(old_string, "old_string")
    new_string = _require_text(new_string, "new_string")
    if not isinstance(replace_all, bool):
        raise EditFileError(
            "'replace_all' must be a boolean.", reason="invalid_argument", argument="replace_all"
        )
    if encoding is not None:
        _require_text(encoding, "encoding")
    if not old_string:
        raise EditFileError("'old_string' must not be empty.", reason="empty_old_string")
    if old_string == new_string:
        raise EditFileError(
            "'old_string' and 'new_string' are identical; there is nothing to change.",
            reason="identical_strings",
        )

    path, root = resolve_write_path(
        file_path, base_dir=base_dir, config=access_config, extra_read_roots=extra_read_roots
    )
    display = _display_path(path, root)
    if not path.exists():
        details: Dict[str, Any] = {"reason": "file_not_found", "file_path": display}
        if file_path != file_path.strip():
            details["hint"] = (
                f"The path carries surrounding whitespace; retry with {file_path.strip()!r}."
            )
        raise EditFileError("File not found.", **details)
    if not path.is_file():
        raise EditFileError(
            "Path is not a regular file (directories and special files are not supported).",
            reason="not_a_file",
            file_path=display,
        )

    before = path.stat()
    raw = _read_bytes(path, display)
    decoded = decode_file_bytes(raw, encoding)
    text = decoded.text

    match_count = text.count(old_string)
    if match_count == 0:
        raise EditFileError(
            "'old_string' was not found; read the file again and copy the exact text, "
            "including surrounding context.",
            reason="no_match",
            file_path=display,
            match_count=0,
            encoding=decoded.encoding,
        )
    if match_count > 1 and not replace_all:
        raise EditFileError(
            f"'old_string' matches {match_count} times; provide more surrounding context to make "
            "it unique, or pass replace_all=true to replace every occurrence.",
            reason="multiple_matches",
            file_path=display,
            match_count=match_count,
            encoding=decoded.encoding,
        )

    ending = dominant_line_ending(text)
    inserted = apply_line_ending(new_string, ending)
    spans = _match_spans(text, old_string, replace_all)
    updated_text = _replace_spans(text, spans, old_string, inserted)
    updated_raw = _splice_bytes(
        raw, text, decoded.bom, decoded.encoding, spans, old_string, inserted, display
    )

    # The byte splice and the text replacement must describe the same file; if
    # they disagree the encoding is not canonical and the write is refused.
    if decode_file_bytes(updated_raw, decoded.encoding).text != updated_text:
        raise EditFileError(
            "The byte-level write does not reproduce the expected text; refusing to write.",
            reason="encoding_mismatch",
            file_path=display,
            encoding=decoded.encoding,
        )

    old_lines = split_lines(text)
    new_lines = split_lines(updated_text)
    groups = _collapsed_groups(
        spans, len(old_string), len(inserted), offsets_from_lines(old_lines), offsets_from_lines(new_lines)
    )

    return _PreparedEdit(
        path=path,
        display=display,
        before=before,
        decoded=decoded,
        spans=spans,
        ending=ending,
        updated_text=updated_text,
        updated_raw=updated_raw,
        old_lines=old_lines,
        new_lines=new_lines,
        groups=groups,
    )


def _git_diff(prepared: _PreparedEdit) -> str:
    """Whole-line patch, with ``\\r`` kept so ``git apply`` accepts it."""
    return build_git_diff(
        prepared.display,
        build_hunks(
            _merge_by_context(prepared.groups, max(len(prepared.old_lines) - 1, 0)),
            prepared.old_lines,
            prepared.new_lines,
            keep_cr=True,
        ),
    )


def _edit_file_impl(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool,
    encoding: Optional[str],
    base_dir: Optional[str],
    access_config: Optional[FileAccessConfig],
    ledger: ReadLedger,
    extra_read_roots: Sequence[Any] = (),
) -> Dict[str, Any]:
    prepared = _prepare_edit(
        file_path,
        old_string,
        new_string,
        replace_all,
        encoding,
        base_dir,
        access_config,
        extra_read_roots,
    )

    before = prepared.before
    after = prepared.path.stat()
    if (after.st_mtime_ns, after.st_size) != (before.st_mtime_ns, before.st_size):
        raise EditFileError(
            "The file changed on disk after it was read; read it again before editing.",
            reason="file_changed",
            file_path=prepared.display,
        )

    try:
        write_bytes_atomic(prepared.path, prepared.updated_raw, stat.S_IMODE(before.st_mode))
    except OSError as exc:
        raise EditFileError(
            f"Cannot write file: {exc}", reason="write_failed", path=prepared.display
        ) from exc

    # Refresh the "whole content is known" mark only when it was already true of
    # the file as this call read it. Otherwise the entry stays stale and a later
    # write_file still reports file_changed instead of trusting it.
    written = prepared.path.stat()
    if ledger.lookup(prepared.path) == (before.st_mtime_ns, before.st_size):
        ledger.record(prepared.path, written.st_mtime_ns, written.st_size)

    return {
        "file_path": prepared.display,
        "encoding": prepared.decoded.encoding,
        "bom": prepared.decoded.has_bom,
        "old_string": old_string,
        "new_string": new_string,
        "inserted_line_ending": prepared.ending,
        "replace_all": bool(replace_all),
        "match_count": len(prepared.spans),
        "original_file": prepared.decoded.text,
        "structured_patch": build_hunks(
            [[group] for group in prepared.groups],
            prepared.old_lines,
            prepared.new_lines,
            keep_cr=False,
        ),
        "gitDiff": _git_diff(prepared),
    }


def make_edit_preview(
    base_dir: Optional[str],
    access_config: Optional[FileAccessConfig] = None,
    extra_read_roots: Sequence[Any] = (),
):
    """A callable returning the diff for a pending edit **without writing it**.

    The confirmation dialog uses it so the user sees the change before deciding
    (ADR 0006 D11). It returns a plain dict that the broker merges into the
    request details. Failures propagate and the caller treats them as "no
    preview", because the tool itself reports the real error once it runs.
    """
    config = access_config if access_config is not None else load_access_config()

    def preview(arguments: Dict[str, Any]) -> Dict[str, Any]:
        prepared = _prepare_edit(
            arguments.get("file_path"),
            arguments.get("old_string", ""),
            arguments.get("new_string", ""),
            bool(arguments.get("replace_all", False)),
            arguments.get("encoding"),
            base_dir,
            config,
            extra_read_roots,
        )
        return {
            "gitDiff": _git_diff(prepared),
            "match_count": len(prepared.spans),
            "encoding": prepared.decoded.encoding,
        }

    return preview


def make_edit_file_tool(
    base_dir: Optional[str],
    access_config: Optional[FileAccessConfig] = None,
    ledger: Optional[ReadLedger] = None,
    extra_read_roots: Sequence[Any] = (),
):
    """Bind the edit tool to a workspace root."""
    config = access_config if access_config is not None else load_access_config()
    read_ledger = ledger if ledger is not None else DEFAULT_LEDGER

    def edit_file(
        file_path: str,
        old_string: str,
        new_string: str = "",
        replace_all: bool = False,
        encoding: Any = None,
    ) -> ToolOutcome:
        try:
            details = _edit_file_impl(
                file_path,
                old_string,
                new_string,
                replace_all,
                encoding,
                base_dir,
                config,
                read_ledger,
                extra_read_roots,
            )
        except (EditFileError, DecodeError, EncodeError) as exc:
            payload = exc.to_dict()
            return ToolOutcome(
                model_text=f"Error: {exc.message}",
                event_category=EventCategory.FILE_EDIT,
                event_title=f"File edit failed: {payload.get('file_path') or file_path}",
                details={"success": False, **payload},
            )
        except AccessDenied as exc:
            payload = exc.to_dict()
            return ToolOutcome(
                model_text=f"Error: {exc.message}",
                event_category=EventCategory.FILE_EDIT,
                event_title=f"File edit denied: {file_path}",
                details={"success": False, **payload},
            )

        return ToolOutcome(
            model_text=f"The file {details['file_path']} has been updated successfully.",
            event_category=EventCategory.FILE_EDIT,
            event_title=f"File edit: {details['file_path']}",
            details={"success": True, **details},
        )

    return edit_file
