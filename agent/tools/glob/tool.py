"""Implementation of the ``glob`` tool: resolve the root, walk, report paths.

The tool's contract is documented in :mod:`agent.tools.glob` (the package
docstring), the description and schema in :mod:`agent.tools.glob.description`,
the pattern semantics in :mod:`agent.tools.glob.pattern`, the walk in
:mod:`agent.tools.glob.search`, and the error type in
:mod:`agent.tools.glob.errors`.

Two things are worth stating here because they connect the tool to the rest of
the file family:

- **The search root goes through ``file_access``**, so a search is exactly as
  confined as a read: inside the workspace, or inside a read-only scratch root,
  and never past the global policy.
- **Returned paths are displayed relative to the workspace root**, which is the
  same base ``read_file`` resolves against. A path the model gets from here is
  therefore usable verbatim, with no rewriting in between.
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
    resolve_read_path,
)
from agent.tools.glob.description import (
    SCAN_TRUNCATED_HINT,
    TRUNCATED_HINT,
)
from agent.tools.glob.errors import GlobError
from agent.tools.glob.search import search_files
from agent.tools.glob_pattern import GlobPattern, split_absolute_pattern


def _clean_pattern(pattern: Any) -> str:
    """Validate ``pattern``; surrounding whitespace is dropped, inner is kept."""
    if not isinstance(pattern, str):
        raise GlobError("'pattern' must be a string.", reason="invalid_argument", argument="pattern")
    text = pattern.strip()
    if not text:
        raise GlobError("'pattern' must not be empty.", reason="invalid_argument", argument="pattern")
    return text


def _clean_path(path: Any) -> Optional[str]:
    """Validate ``path`` without rewriting it (a directory may end in spaces)."""
    if path is None:
        return None
    if not isinstance(path, str):
        raise GlobError("'path' must be a string.", reason="invalid_argument", argument="path")
    return path if path.strip() else None


def _search_root(
    pattern: str,
    requested: Optional[str],
    base_dir: Optional[str],
    config: Optional[FileAccessConfig],
    extra_read_roots: Sequence[Any],
) -> Tuple[Path, str, Optional[Path]]:
    """Resolve where to search and which pattern to apply there.

    Returns ``(root, pattern, workspace_root)``. An absolute pattern brings its
    own root and wins over ``path``; otherwise ``path`` (or the workspace root)
    is the place to start.
    """
    absolute = split_absolute_pattern(pattern)
    target = requested
    if absolute is not None:
        target, pattern = absolute

    candidate = target if target else "."
    root, workspace = resolve_read_path(
        candidate,
        base_dir=base_dir,
        config=config,
        extra_read_roots=extra_read_roots,
    )
    if not root.exists():
        raise GlobError(
            "Search path not found.",
            reason="path_not_found",
            path=display_path(root, workspace),
        )
    if not root.is_dir():
        raise GlobError(
            "Search path is not a directory; pass a directory in 'path' (or drop it) and "
            "describe the files with 'pattern'.",
            reason="not_a_directory",
            path=display_path(root, workspace),
        )
    return root, pattern, workspace


def _build_payload(
    effective_pattern: str,
    root: Path,
    workspace: Optional[Path],
    files: List[str],
    duration_ms: int,
    truncated: bool,
    scan_truncated: bool,
    scanned: int,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "pattern": effective_pattern,
        "path": display_path(root, workspace),
        "filenames": files,
        "num_files": len(files),
        "duration_ms": duration_ms,
        "truncated": truncated,
    }
    if scan_truncated:
        payload["scan_truncated"] = True
        payload["scanned_entries"] = scanned
    if truncated:
        payload["hint"] = SCAN_TRUNCATED_HINT if scan_truncated else TRUNCATED_HINT
    return payload


def _glob_impl(
    pattern: Any,
    path: Any,
    base_dir: Optional[str],
    config: Optional[FileAccessConfig],
    extra_read_roots: Sequence[Any],
) -> Dict[str, Any]:
    cleaned = _clean_pattern(pattern)
    requested = _clean_path(path)
    started = time.monotonic()

    root, effective, workspace = _search_root(
        cleaned, requested, base_dir, config, extra_read_roots
    )
    result = search_files(root, GlobPattern(effective), policy=config)
    files = [display_path(item, workspace) for item in result.files]

    return _build_payload(
        effective,
        root,
        workspace,
        files,
        int((time.monotonic() - started) * 1000),
        result.truncated,
        result.scan_truncated,
        result.scanned,
    )


def make_glob_tool(
    base_dir: Optional[str],
    access_config: Optional[FileAccessConfig] = None,
    extra_read_roots: Sequence[Any] = (),
):
    """Bind the search tool to a workspace root and the active access policy."""
    config = access_config if access_config is not None else load_access_config()

    def glob_files(pattern: str, path: Any = None) -> Dict[str, Any]:
        try:
            return _glob_impl(pattern, path, base_dir, config, extra_read_roots)
        except GlobError as exc:
            return exc.to_dict()
        except AccessDenied as exc:
            return exc.to_dict()

    return glob_files
