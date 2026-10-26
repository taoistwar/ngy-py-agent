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

The one exception is :func:`workspace_result_directory`: persisted *tool results*
(``<workspace>/.task_outputs/tool-results``) live inside the workspace instead, so a
later turn of the same session can still reach them by their absolute path
(ADR 0012). They are registered as a read-only root, exactly like this tree.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from agent.tools.file_access import default_workspace_root

OUTPUT_DIR_ENV = "EXEC_OUTPUT_DIR"
DEFAULT_OUTPUT_DIR_NAME = ("ngy-py-agent", "output")

# Persisted tool results: workspace-relative, so they outlive the temp tree.
RESULT_DIR_NAME = ".task_outputs"
RESULT_SUBDIR_NAME = "tool-results"
RESULT_GITIGNORE = "*\n"

# Archived conversations (ADR 0015): same workspace, same read-only treatment.
TRANSCRIPT_DIR_NAME = ".transcripts"

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


def workspace_result_directory(base_dir: Optional[str] = None) -> Path:
    """Where persisted *tool results* go: ``<workspace>/.task_outputs/tool-results``.

    Inside the workspace on purpose (ADR 0012): a session keeps the absolute path of
    every result it moved out of the context, so the files must still be there when a
    follow-up turn reads one back. Unlike this module's temp tree, nothing prunes
    them; that is the caller's call, not a side effect of reading.

    The directory is registered as a read-only root, so the file tools can read a
    result but never rewrite it: a result the model can edit is a result it can
    mistake for the original.

    Not created here - deciding where output would go must not leave a folder
    behind. Writers call :func:`ensure_dir` (or :func:`persist_text`).
    """
    return _workspace_directory(base_dir, RESULT_DIR_NAME, RESULT_SUBDIR_NAME)


def workspace_transcript_directory(base_dir: Optional[str] = None) -> Path:
    """Where archived conversations go: ``<workspace>/.transcripts``.

    The same reasoning as :func:`workspace_result_directory` (ADR 0015): the archive
    marker keeps an absolute path, and the message it replaced is gone from the
    conversation, so the file has to outlive the run that wrote it.

    Not created here; writers call :func:`ensure_result_directory`.
    """
    return _workspace_directory(base_dir, TRANSCRIPT_DIR_NAME)


def _workspace_directory(base_dir: Optional[str], *parts: str) -> Path:
    text = (base_dir or "").strip()
    root = Path(text).expanduser() if text else default_workspace_root()
    try:
        root = root.resolve()
    except OSError:  # pragma: no cover - platform specific
        root = root.absolute()
    return root.joinpath(*parts)


def ensure_result_directory(directory: Path) -> Path:
    """Create a persisted-output directory (results or transcripts) and ignore it in git.

    A nested ``.gitignore`` holding ``*`` instead of an entry in the workspace's own
    ignore file: the workspace belongs to the user, and appending to their rules on
    our every run is not ours to do. Nested rules make the folder disappear from
    ``git status`` while the delete of the folder takes the rule with it.
    """
    ensure_dir(directory)
    ignore = directory / ".gitignore"
    if not ignore.exists():
        try:
            ignore.write_text(RESULT_GITIGNORE, encoding="utf-8")
        except OSError:
            # Losing the rule is cosmetic; losing the result is not. The caller
            # reports the failure that actually matters when it writes the result.
            pass
    return directory


def new_stem(prefix: str = "") -> str:
    """A collision-resistant name stem shared by everything that persists output.

    Timestamp first so a directory listing is chronological, plus a short random
    suffix so two commands in the same second cannot collide.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}{stamp}-{uuid.uuid4().hex[:6]}"


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
