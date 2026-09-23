"""The edit pipeline: read, match, splice and verify - then write, if asked.

Everything up to the write has no side effects, which is what makes the
confirmation preview possible (ADR 0006 D11). The write itself is atomic and
re-checks that the file did not change underneath the call.
"""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from agent.tools.edit_file import diff, replace
from agent.tools.edit_file.errors import EditFileError
from agent.tools.file_access import FileAccessConfig, load_access_config, resolve_write_path
from agent.tools.file_bytes import write_bytes_atomic
from agent.tools.read_ledger import ReadLedger
from agent.tools.text_encoding import decode_file_bytes
from agent.tools.text_lines import (
    apply_line_ending,
    dominant_line_ending,
    offsets_from_lines,
    split_lines,
)


def display_path(path: Path, root: Optional[Path]) -> str:
    if root is None:
        return path.as_posix()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def require_text(value: Any, argument: str) -> str:
    """Reject non-string arguments instead of letting them raise ``TypeError``."""
    if not isinstance(value, str):
        raise EditFileError(
            f"'{argument}' must be a string.", reason="invalid_argument", argument=argument
        )
    return value


def read_bytes(path: Path, display: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise EditFileError(
            f"Cannot read file: {exc}", reason="read_failed", file_path=display
        ) from exc


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


def prepare_edit(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool,
    encoding: Optional[str],
    base_dir: Optional[str],
    access_config: Optional[FileAccessConfig],
    extra_read_roots: Sequence[Any] = (),
) -> _PreparedEdit:
    """Do everything except the write, so the result can also be shown as a diff."""
    if not isinstance(file_path, str) or not file_path.strip():
        raise EditFileError(
            "'file_path' must be a non-empty string.", reason="invalid_argument", argument="file_path"
        )
    old_string = require_text(old_string, "old_string")
    new_string = require_text(new_string, "new_string")
    if not isinstance(replace_all, bool):
        raise EditFileError(
            "'replace_all' must be a boolean.", reason="invalid_argument", argument="replace_all"
        )
    if encoding is not None:
        require_text(encoding, "encoding")
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
    display = display_path(path, root)
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
    raw = read_bytes(path, display)
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
    spans = replace.match_spans(text, old_string, replace_all)
    updated_text = replace.replace_spans(text, spans, old_string, inserted)
    updated_raw = replace.splice_bytes(
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
    groups = diff.collapsed_groups(
        spans,
        len(old_string),
        len(inserted),
        offsets_from_lines(old_lines),
        offsets_from_lines(new_lines),
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


def edit_file_impl(
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
    """Prepare the edit and, when nothing moved underneath us, write it."""
    prepared = prepare_edit(
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
        "structured_patch": diff.build_patch(prepared.groups, prepared.old_lines, prepared.new_lines),
        "gitDiff": diff.build_diff(
            prepared.display, prepared.groups, prepared.old_lines, prepared.new_lines
        ),
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
        prepared = prepare_edit(
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
            "gitDiff": diff.build_diff(
                prepared.display, prepared.groups, prepared.old_lines, prepared.new_lines
            ),
            "match_count": len(prepared.spans),
            "encoding": prepared.decoded.encoding,
        }

    return preview
