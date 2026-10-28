"""Where a workspace's checkpoint repository lives, and what its refs are called.

Everything here is naming and path arithmetic: no git, no I/O beyond ``Path.is_dir``.
Kept apart from the store so that "which directory does this key mean" can be read
without reading the snapshot logic (ADR 0020 D2).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

from agent.tools.file_access import default_workspace_root

STORE_ROOT_ENV = "CHECKPOINT_ROOT"
ENABLED_ENV = "CHECKPOINT_ENABLED"
DEFAULT_STORE_DIRNAME = "data/checkpoints"

# Branch names: one task, one history, plus the commit it started from.
BRANCH_PREFIX = "cp"
BASE_SUFFIX = "-base"


def enabled() -> bool:
    """Whether checkpointing is switched on at all. Off means "behave as before"."""
    raw = (os.getenv(ENABLED_ENV) or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def store_root() -> Path:
    """The directory holding every workspace's repository."""
    override = (os.getenv(STORE_ROOT_ENV) or "").strip()
    return Path(override).expanduser() if override else Path.cwd() / DEFAULT_STORE_DIRNAME


def workspace_key(workspace: Path) -> str:
    """A stable, filesystem-safe name for one workspace.

    Case-folded on Windows: the same directory reached through two spellings must not
    end up as two repositories, or a revert would look at the wrong history.
    """
    identity = str(workspace)
    if os.name == "nt":
        identity = identity.lower()
    return hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]


def ref_component(task_id: str) -> str:
    """A task id that is legal inside a git ref name.

    Task ids are usually bare uuids, but a ref name forbids ``~^:?*[`` and a space, so
    anything unusual is escaped and then disambiguated with a short hash - two
    different ids must never collapse onto the same branch.
    """
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in task_id)
    if safe != task_id:
        safe = f"{safe[:24]}-{hashlib.sha1(task_id.encode('utf-8')).hexdigest()[:8]}"
    return safe


def normalized(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:  # pragma: no cover - platform specific
        return path.absolute()


def workspace_path(base_dir: Optional[str]) -> Optional[Path]:
    """The directory a run writes into, or ``None`` when there is not one yet.

    Mirrors how the file tools resolve a relative path: the bound ``base_dir`` when
    there is one, the session default workspace otherwise (ADR 0007).
    """
    text = (base_dir or "").strip()
    if text:
        candidate = normalized(Path(text).expanduser())
    else:
        candidate = normalized(default_workspace_root())
    return candidate if candidate.is_dir() else None
