"""Where large tool output goes, and how the model gets it back.

A command can print megabytes; the model's context cannot hold that. Output above
the token budget is written to disk and the model receives a short preview plus the
path, which it reads back in slices with ``read_file``.

Layout::

    <temp>/ngy-py-agent/output/<workspace>/<scope>/<name>

- ``<workspace>`` is the sanitised workspace root (or ``unbound``), ``<scope>`` the
  session or task id, so two runs never share a directory.
- The tree lives **outside the workspace** on purpose: it must not pollute the
  project or show up in git.
- ``read_file`` reaches it through an *additional readable root* that is readable
  but never writable (see ``docs/decisions/0005-exec-tool.md``).

Files here are scratch. Nothing prunes them automatically; the OS temp cleaner
does, and a runaway command is bounded by its timeout instead.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

OUTPUT_DIR_ENV = "EXEC_OUTPUT_DIR"
DEFAULT_OUTPUT_DIR_NAME = ("ngy-py-agent", "output")

# Preview kept in the model's context when the full output is persisted.
DEFAULT_PREVIEW_CHARS = 2000

UNBOUND_WORKSPACE = "unbound"
DEFAULT_SCOPE = "default"

_SLUG_KEEP = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(value: str, limit: int = 32) -> str:
    """A readable-but-collision-free directory name for an arbitrary path."""
    digest = hashlib.sha1(value.encode("utf-8", errors="replace")).hexdigest()[:8]
    cleaned = _SLUG_KEEP.sub("-", value).strip("-")[:limit]
    return f"{cleaned}-{digest}" if cleaned else digest


def output_base_dir() -> Path:
    """Root of the persisted-output tree (overridable for tests and operators)."""
    override = (os.getenv(OUTPUT_DIR_ENV) or "").strip()
    if override:
        return Path(override).expanduser()
    return Path(tempfile.gettempdir()).joinpath(*DEFAULT_OUTPUT_DIR_NAME)


def output_root_path(base_dir: Optional[str] = None, scope: Optional[str] = None) -> Path:
    """This run's output directory.

    Deliberately does **not** create it: a registry is built for every run, even
    ones that never execute a command, and creating temp directories as a side
    effect of construction is noise. Writers call :func:`ensure_dir`.
    """
    return output_base_dir() / _slug((base_dir or "").strip() or UNBOUND_WORKSPACE) / _slug(
        (scope or "").strip() or DEFAULT_SCOPE
    )


def ensure_dir(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def output_root(base_dir: Optional[str] = None, scope: Optional[str] = None) -> Path:
    """Like :func:`output_root_path`, but creates the directory."""
    return ensure_dir(output_root_path(base_dir, scope))


def persist_text(directory: Path, name: str, text: str) -> Path:
    """Write ``text`` byte-exactly (no newline translation) and return the path."""
    path = ensure_dir(directory) / name
    path.write_bytes(text.encode("utf-8", errors="replace"))
    return path


def write_pid_file(directory: Path, name: str, info: Dict[str, Any]) -> Path:
    """Record what was started, for identification after a crash or a restart.

    Never the kill mechanism: pids get recycled and these files go stale.
    """
    path = ensure_dir(directory) / name
    path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def preview(text: str, limit: int = DEFAULT_PREVIEW_CHARS) -> str:
    """The head of ``text``, with a marker when something was left out."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated: {len(text) - limit} more characters in the persisted file]\n"


def describe_size(text: str) -> Dict[str, Any]:
    return {"characters": len(text), "bytes": len(text.encode("utf-8", errors="replace"))}
