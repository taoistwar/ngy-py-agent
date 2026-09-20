"""Access policy shared by the file tools (read and edit).

Two layers of confinement are applied together:

- **Workspace root** - when the session is bound to a workspace (``base_dir``),
  paths resolve against it and may never leave it.
- **Global policy** - applied in every case, bound or not:

  * ``deny_dirs``: these directories and everything below them are off limits.
  * ``deny_files``: these exact files are off limits.
  * ``allow_dirs``: when non-empty, only files below these directories may be accessed.

  Deny rules always win over allow rules.

The policy lives in a JSON file (``FILE_ACCESS_CONFIG`` to relocate it, default
``data/file_access.json``). A missing or unreadable file means "no policy".

**Additional read roots** are a third, per-run layer: directories outside the
workspace that may be *read* but never written (currently the persisted output
tree of ``exec``). This is a deliberate exception to "a file you can read, you can
edit" - scratch output is not project content. The global policy still applies on
top, so a deny rule or a non-empty ``allow_dirs`` can keep them unreachable.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

CONFIG_ENV = "FILE_ACCESS_CONFIG"
DEFAULT_CONFIG_PATH = "data/file_access.json"

REASON_DENY_DIR = "deny_dir"
REASON_DENY_FILE = "deny_file"
REASON_OUTSIDE_ALLOW = "outside_allow_dirs"
REASON_OUTSIDE_WORKSPACE = "outside_workspace"
REASON_READ_ONLY_ROOT = "read_only_root"


class AccessDenied(Exception):
    """Raised when a path is not readable under the active policy."""

    def __init__(self, message: str, path: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.path = path
        self.reason = reason

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, "path": self.path, "reason": self.reason}


@dataclass(frozen=True)
class FileAccessConfig:
    """Global allow/deny lists applied when no workspace root is set."""

    deny_dirs: Tuple[Path, ...] = ()
    deny_files: Tuple[Path, ...] = ()
    allow_dirs: Tuple[Path, ...] = ()

    @classmethod
    def from_dict(cls, payload: Any) -> "FileAccessConfig":
        if not isinstance(payload, dict):
            return cls()
        return cls(
            deny_dirs=_to_paths(payload.get("deny_dirs")),
            deny_files=_to_paths(payload.get("deny_files")),
            allow_dirs=_to_paths(payload.get("allow_dirs")),
        )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:  # pragma: no cover - platform specific
        return path.absolute()


def _to_paths(values: Any) -> Tuple[Path, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    collected = []
    for value in values:
        text = str(value or "").strip()
        if text:
            collected.append(_normalize(Path(text).expanduser()))
    return tuple(collected)


def config_path() -> Path:
    """Location of the global policy file."""
    override = (os.getenv(CONFIG_ENV) or "").strip()
    if override:
        return Path(override).expanduser()
    return _repo_root() / DEFAULT_CONFIG_PATH


def load_access_config(path: Optional[Path] = None) -> FileAccessConfig:
    """Load the global policy, returning an empty one when unavailable."""
    target = path or config_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return FileAccessConfig()
    return FileAccessConfig.from_dict(payload)


def is_within(path: Path, root: Path) -> bool:
    """Case-insensitive containment check that also works on Windows."""
    candidate = os.path.normcase(str(path))
    base = os.path.normcase(str(root))
    return candidate == base or candidate.startswith(base + os.sep)


def _same_file(path: Path, other: Path) -> bool:
    return os.path.normcase(str(path)) == os.path.normcase(str(other))


def enforce_policy(path: Path, config: FileAccessConfig, action: str = "read") -> None:
    """Raise :class:`AccessDenied` when ``path`` violates the global policy."""
    display = path.as_posix()

    for denied_file in config.deny_files:
        if _same_file(path, denied_file):
            raise AccessDenied(
                "This file is blocked by the global deny list.", display, REASON_DENY_FILE
            )

    for denied_dir in config.deny_dirs:
        if is_within(path, denied_dir):
            raise AccessDenied(
                "This directory is blocked by the global deny list.",
                display,
                REASON_DENY_DIR,
            )

    if config.allow_dirs and not any(is_within(path, item) for item in config.allow_dirs):
        raise AccessDenied(
            f"Only files inside the global allow list can be {action}.",
            display,
            REASON_OUTSIDE_ALLOW,
        )


def _workspace_root(base_dir: Optional[str]) -> Optional[Path]:
    text = (base_dir or "").strip()
    return _normalize(Path(text)) if text else None


def _normalized_roots(extra_read_roots: Sequence[Any]) -> Tuple[Path, ...]:
    roots = []
    for item in extra_read_roots or ():
        text = str(item or "").strip()
        if text:
            roots.append(_normalize(Path(text).expanduser()))
    return tuple(roots)


def _resolve_path(
    file_path: str,
    base_dir: Optional[str],
    config: Optional[FileAccessConfig],
    action: str,
    extra_read_roots: Sequence[Any] = (),
) -> Tuple[Path, Optional[Path]]:
    """Resolve ``file_path`` and enforce the workspace root, extra roots and policy.

    Returns ``(resolved_path, workspace_root)`` where ``workspace_root`` is
    ``None`` for unbound sessions.

    A path inside an *additional read root* is readable but never modifiable, and
    the global policy is still applied to it - a deny rule or a non-empty
    ``allow_dirs`` keeps working, it is only the workspace ceiling that is lifted.
    """
    root = _workspace_root(base_dir)
    candidate = Path(file_path)
    if not candidate.is_absolute():
        candidate = (root or Path.cwd()) / candidate
    resolved = _normalize(candidate)

    if any(is_within(resolved, extra) for extra in _normalized_roots(extra_read_roots)):
        if action == "modified":
            raise AccessDenied(
                "This is the read-only scratch area for tool output; it can be read but not "
                "modified. Write to the workspace instead.",
                resolved.as_posix(),
                REASON_READ_ONLY_ROOT,
            )
        enforce_policy(resolved, config or FileAccessConfig(), action=action)
        return resolved, root

    if root is not None and not is_within(resolved, root):
        raise AccessDenied(
            f"Path escapes the workspace root; only files inside the workspace can be {action}.",
            resolved.as_posix(),
            REASON_OUTSIDE_WORKSPACE,
        )

    enforce_policy(resolved, config or FileAccessConfig(), action=action)
    return resolved, root


def resolve_read_path(
    file_path: str,
    base_dir: Optional[str] = None,
    config: Optional[FileAccessConfig] = None,
    extra_read_roots: Sequence[Any] = (),
) -> Tuple[Path, Optional[Path]]:
    """Resolve ``file_path`` for reading, including the additional read roots."""
    return _resolve_path(file_path, base_dir, config, "read", extra_read_roots)


def resolve_write_path(
    file_path: str,
    base_dir: Optional[str] = None,
    config: Optional[FileAccessConfig] = None,
    extra_read_roots: Sequence[Any] = (),
) -> Tuple[Path, Optional[Path]]:
    """Resolve ``file_path`` for writing.

    Writes reuse the read policy on purpose - a file you can read, you can edit
    (see ``docs/decisions/0001-file-edit-tool.md``) - with one exception: the
    additional read roots are refused, because they are scratch output rather than
    project content (see ``docs/decisions/0005-exec-tool.md``).
    """
    return _resolve_path(file_path, base_dir, config, "modified", extra_read_roots)
