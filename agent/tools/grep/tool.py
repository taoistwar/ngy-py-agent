"""Implementation of the ``grep`` tool: validate, resolve, scan, report.

The tool's contract is in :mod:`agent.tools.grep` (package docstring) and
:mod:`agent.tools.grep.description`; the disk work is in
:mod:`agent.tools.grep.scan`, the three output shapes in
:mod:`agent.tools.grep.content` and :mod:`agent.tools.grep.listing`, and the
pattern compilation in :mod:`agent.tools.grep.regex`.

Argument handling is deliberately forgiving about *shape* and strict about
*meaning*: ``"3"`` for ``context`` and ``"true"`` for ``case_insensitive`` are
accepted (models produce them), while a negative count, an unknown
``output_mode`` or an unknown ``type`` is refused with the accepted values -
guessing there would return a plausible, wrong answer.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agent.tools.file_access import (
    AccessDenied,
    FileAccessConfig,
    display_path,
    load_access_config,
)
from agent.tools.glob_pattern import GlobPattern
from agent.tools.grep.content import ContentOptions, collect_content
from agent.tools.grep.description import (
    DEFAULT_HEAD_LIMIT,
    MAX_DURATION_SECONDS,
    MODE_CONTENT,
    MODE_COUNT,
    MODE_FILES,
    NO_MATCH_HINT,
    OFFSET_PAST_END_HINT,
    OUTPUT_MODES,
    SKIPPED_ONLY_HINT,
    TRUNCATED_HINT,
)
from agent.tools.grep.errors import GrepError
from agent.tools.grep.listing import collect_counts, collect_files
from agent.tools.grep.regex import compile_pattern
from agent.tools.grep.scan import CandidateSet, collect_candidates, resolve_root
from agent.tools.grep.types import extensions_for, supported_types

# ----------------------------------------------------------------- arguments


def _clean_pattern(value: Any) -> str:
    if not isinstance(value, str):
        raise GrepError("'pattern' must be a string.", reason="invalid_argument", argument="pattern")
    if not value.strip():
        raise GrepError("'pattern' must not be empty.", reason="invalid_argument", argument="pattern")
    return value


def _clean_optional(value: Any, name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GrepError(f"'{name}' must be a string.", reason="invalid_argument", argument=name)
    return value if value.strip() else None


def _as_bool(value: Any, name: str, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off", ""):
        return False
    raise GrepError(
        f"'{name}' must be a boolean.", reason="invalid_argument", argument=name
    )


def _as_count(value: Any, name: str, default: int = 0) -> int:
    """A non-negative integer argument, tolerating a numeric string."""
    if value is None:
        return default
    if isinstance(value, bool):
        raise GrepError(
            f"'{name}' must be an integer.", reason="invalid_argument", argument=name
        )
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise GrepError(
            f"'{name}' must be an integer.", reason="invalid_argument", argument=name
        ) from None
    if number < 0:
        raise GrepError(
            f"'{name}' must not be negative.", reason="invalid_argument", argument=name
        )
    return number


def _as_limit(value: Any) -> Optional[int]:
    """Output cap; ``0`` means "no cap", which is the only way to lift it."""
    number = _as_count(value, "head_limit", DEFAULT_HEAD_LIMIT)
    return None if number == 0 else number


def _clean_mode(value: Any) -> str:
    text = (str(value).strip().lower() if value is not None else "") or MODE_FILES
    if text not in OUTPUT_MODES:
        raise GrepError(
            f"Unknown 'output_mode' {text!r}.",
            reason="invalid_argument",
            argument="output_mode",
            allowed=list(OUTPUT_MODES),
        )
    return text


def _clean_type(value: Any) -> Optional[Tuple[str, ...]]:
    name = _clean_optional(value, "type")
    if name is None:
        return None
    extensions = extensions_for(name)
    if extensions is None:
        raise GrepError(
            f"Unknown file 'type' {name!r}.",
            reason="unknown_type",
            argument="type",
            supported=list(supported_types()),
        )
    return extensions


def _clean_glob(value: Any) -> Optional[GlobPattern]:
    """The file filter; several patterns may be given, comma or space separated."""
    text = _clean_optional(value, "glob")
    if text is None:
        return None
    patterns = _split_filters(text)
    if not patterns:  # pragma: no cover - defensive: separators only was rejected above
        return None
    combined = patterns[0] if len(patterns) == 1 else "{" + ",".join(patterns) + "}"
    return GlobPattern(combined)


def _split_filters(text: str) -> List[str]:
    """Split on commas/whitespace, keeping ``{a,b}`` alternatives intact."""
    patterns: List[str] = []
    current: List[str] = []
    depth = 0
    for char in text:
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(depth - 1, 0)
        if depth == 0 and (char == "," or char.isspace()):
            if current:
                patterns.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        patterns.append("".join(current))
    return patterns


# ------------------------------------------------------------------- payload


def _apply_signals(
    payload: Dict[str, Any],
    candidates: CandidateSet,
    timed_out: bool,
    skipped: Sequence[str],
) -> None:
    """Attach the "the answer is incomplete, and here is why" fields."""
    # The walk and the scan share one budget, so either of them can be the part
    # that ran out of time.
    if timed_out or candidates.timed_out:
        payload["timed_out"] = True
    if candidates.scan_truncated:
        payload["scan_truncated"] = True
        payload["scanned_entries"] = candidates.scanned
    if skipped:
        payload["skipped_sensitive"] = list(skipped)


def _apply_hint(
    payload: Dict[str, Any],
    *,
    has_results: bool,
    truncated: bool,
    skipped: Sequence[str],
    found: int,
    offset: int,
) -> None:
    """Explain an empty or partial answer; a full page needs no explanation."""
    if truncated:
        payload["hint"] = TRUNCATED_HINT
    elif has_results:
        return
    elif offset and found:
        # There were results, just not at this offset. Saying "no matches" here
        # sends the model off to rewrite a pattern that was already right.
        payload["hint"] = OFFSET_PAST_END_HINT
    elif skipped:
        payload["hint"] = SKIPPED_ONLY_HINT
    else:
        payload["hint"] = NO_MATCH_HINT


def _apply_pagination(payload: Dict[str, Any], truncated: bool, limit: Optional[int], offset: int):
    """Say which page this was, but only when there is another one."""
    if not truncated:
        return
    if limit is not None:
        payload["applied_limit"] = limit
    payload["applied_offset"] = offset


def _content_payload(
    outcome, candidates: CandidateSet, limit: Optional[int], offset: int
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "mode": MODE_CONTENT,
        "content": "\n".join(outcome.lines),
        "num_lines": len(outcome.lines),
        "truncated": outcome.truncated,
    }
    _apply_pagination(payload, outcome.truncated, limit, offset)
    _apply_signals(payload, candidates, outcome.timed_out, candidates.skipped_sensitive)
    _apply_hint(
        payload,
        has_results=bool(outcome.lines),
        truncated=outcome.truncated,
        skipped=candidates.skipped_sensitive,
        found=outcome.found,
        offset=offset,
    )
    return payload


def _files_payload(
    outcome, workspace: Optional[Path], candidates: CandidateSet, limit, offset
) -> Dict[str, Any]:
    files = [display_path(path, workspace) for path in outcome.files]
    payload: Dict[str, Any] = {
        "mode": MODE_FILES,
        "filenames": files,
        "num_files": len(files),
        "truncated": outcome.truncated,
    }
    _apply_pagination(payload, outcome.truncated, limit, offset)
    _apply_signals(payload, candidates, outcome.timed_out, candidates.skipped_sensitive)
    _apply_hint(
        payload,
        has_results=bool(files),
        truncated=outcome.truncated,
        skipped=candidates.skipped_sensitive,
        found=outcome.found,
        offset=offset,
    )
    return payload


def _count_payload(
    outcome, workspace: Optional[Path], candidates: CandidateSet, limit, offset
) -> Dict[str, Any]:
    lines = [f"{display_path(path, workspace)}:{count}" for path, count in outcome.counts]
    payload: Dict[str, Any] = {
        "mode": MODE_COUNT,
        "content": "\n".join(lines),
        "num_files": len(lines),
        "num_matches": outcome.total,
        "truncated": outcome.truncated,
    }
    _apply_pagination(payload, outcome.truncated, limit, offset)
    _apply_signals(payload, candidates, outcome.timed_out, candidates.skipped_sensitive)
    _apply_hint(
        payload,
        has_results=bool(lines),
        truncated=outcome.truncated,
        skipped=candidates.skipped_sensitive,
        found=outcome.found,
        offset=offset,
    )
    return payload


# ---------------------------------------------------------------- the search


def _grep_impl(
    pattern: Any,
    path: Any,
    glob_filter: Any,
    file_type: Any,
    output_mode: Any,
    case_insensitive: Any,
    multiline: Any,
    line_numbers: Any,
    context: Any,
    before_context: Any,
    after_context: Any,
    head_limit: Any,
    offset: Any,
    base_dir: Optional[str],
    config: Optional[FileAccessConfig],
    extra_read_roots: Sequence[Any],
) -> Dict[str, Any]:
    started = time.monotonic()

    cleaned = _clean_pattern(pattern)
    mode = _clean_mode(output_mode)
    matcher = _clean_glob(glob_filter)
    extensions = _clean_type(file_type)
    span_lines = _as_bool(multiline, "multiline")
    regex = compile_pattern(
        cleaned,
        case_insensitive=_as_bool(case_insensitive, "case_insensitive"),
        multiline=span_lines,
    )
    # ``context`` wins over the one-sided knobs, which is the order ripgrep uses.
    before = _as_count(context if context is not None else before_context, "context")
    after = _as_count(context if context is not None else after_context, "context")
    limit = _as_limit(head_limit)
    skip = _as_count(offset, "offset")

    root, workspace = resolve_root(
        _clean_optional(path, "path"), base_dir, config, extra_read_roots
    )
    # One budget for the whole call: walking and reading share it, so a slow tree
    # cannot consume the time the scan itself needs (or the other way round).
    deadline = started + MAX_DURATION_SECONDS
    candidates = collect_candidates(root, workspace, matcher, extensions, config, deadline)

    if mode == MODE_CONTENT:
        options = ContentOptions(
            offset=skip,
            limit=limit,
            before=before,
            after=after,
            line_numbers=_as_bool(line_numbers, "line_numbers", default=True),
            multiline=span_lines,
        )
        outcome = collect_content(candidates.files, regex, options, deadline, workspace)
        payload = _content_payload(outcome, candidates, limit, skip)
    elif mode == MODE_COUNT:
        outcome = collect_counts(candidates.files, regex, skip, limit, deadline, span_lines)
        payload = _count_payload(outcome, workspace, candidates, limit, skip)
    else:
        outcome = collect_files(candidates.files, regex, skip, limit, deadline, span_lines)
        payload = _files_payload(outcome, workspace, candidates, limit, skip)

    payload["duration_ms"] = int((time.monotonic() - started) * 1000)
    return payload


def make_grep_tool(
    base_dir: Optional[str],
    access_config: Optional[FileAccessConfig] = None,
    extra_read_roots: Sequence[Any] = (),
):
    """Bind the search tool to a workspace root and the active access policy."""
    config = access_config if access_config is not None else load_access_config()

    # ``glob`` and ``type`` are the model-visible names, so the handler has to
    # accept them; they are renamed on the way in to keep the internals readable.
    def grep_files(
        pattern: str,
        path: Any = None,
        glob: Any = None,
        type: Any = None,
        output_mode: Any = None,
        case_insensitive: Any = None,
        multiline: Any = None,
        line_numbers: Any = None,
        context: Any = None,
        before_context: Any = None,
        after_context: Any = None,
        head_limit: Any = None,
        offset: Any = None,
    ) -> Dict[str, Any]:
        try:
            return _grep_impl(
                pattern,
                path,
                glob,
                type,
                output_mode,
                case_insensitive,
                multiline,
                line_numbers,
                context,
                before_context,
                after_context,
                head_limit,
                offset,
                base_dir,
                config,
                extra_read_roots,
            )
        except GrepError as exc:
            return exc.to_dict()
        except AccessDenied as exc:
            return exc.to_dict()

    return grep_files
