"""A guarded wrapper over the ``git`` binary.

The checkpoint store keeps its repository **outside** the workspace and always
addresses it with an explicit ``--git-dir``/``--work-tree`` pair, so nothing here can
reach the user's own repository, index or ``.git`` directory.

Two settings are not negotiable:

- ``core.autocrlf=false``: the store records bytes. Any line-ending conversion would
  make a revert rewrite files the task never touched.
- an explicit ``user.name``/``user.email``: a machine with no global git identity must
  still be able to record a checkpoint, and a checkpoint is not the user's commit.

Every call is bounded by a timeout and stripped of interactive prompts: a hung or
waiting-for-a-password git must not hang a task (see ADR 0020).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional, Sequence

GIT_TIMEOUT_SECONDS = 60.0
GIT_BINARY_ENV = "CHECKPOINT_GIT"

# Recorded as the store's own identity. Not the user's: these commits live in a
# private repository the user never sees.
_AUTHOR_NAME = "ngy-py-agent checkpoint"
_AUTHOR_EMAIL = "checkpoint@localhost"

_CONFIG: Sequence[str] = (
    f"user.name={_AUTHOR_NAME}",
    f"user.email={_AUTHOR_EMAIL}",
    # The repository is bare on purpose - it has no work tree of its own, and the one
    # it operates on is passed in on every call - so it has to be told that having a
    # work tree is not a contradiction.
    "core.bare=false",
    "core.autocrlf=false",
    "core.safecrlf=false",
    "core.fileMode=false",
    # Keep non-ASCII paths literal in output instead of octal-escaped, so a path
    # read back from git is the path on disk.
    "core.quotepath=false",
    "commit.gpgsign=false",
)


class GitError(RuntimeError):
    """A git call the store could not complete."""


def binary() -> str:
    """The git executable to use; overridable for tests and unusual installs."""
    return (os.getenv(GIT_BINARY_ENV) or "git").strip() or "git"


def _env() -> dict:
    env = dict(os.environ)
    # Never prompt, never wait for a lock the caller did not ask for, and never
    # inherit a repository from the calling shell.
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_ASKPASS"] = ""
    for inherited in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(inherited, None)
    return env


_AVAILABLE: Optional[bool] = None


def available() -> bool:
    """Whether a usable git binary is on this machine.

    Probed once and remembered: the answer cannot change while the process runs, and
    the probe runs on the first checkpoint rather than at import.
    """
    global _AVAILABLE
    if _AVAILABLE is None:
        try:
            completed = subprocess.run(
                [binary(), "--version"],
                capture_output=True,
                timeout=GIT_TIMEOUT_SECONDS,
                env=_env(),
            )
            _AVAILABLE = completed.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _AVAILABLE = False
    return bool(_AVAILABLE)


def reset_availability_cache() -> None:
    """Forget the probe result. For tests that swap the binary or its absence."""
    global _AVAILABLE
    _AVAILABLE = None


def _command(git_dir: Path, work_tree: Path, args: Sequence[str]) -> list[str]:
    command = [binary(), f"--git-dir={git_dir}", f"--work-tree={work_tree}"]
    for setting in _CONFIG:
        command.extend(["-c", setting])
    command.extend(args)
    return command


def _invoke(
    command: Sequence[str],
    work_tree: Optional[Path],
    timeout: float,
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            list(command),
            cwd=str(work_tree) if work_tree is not None else None,
            capture_output=True,
            timeout=timeout,
            env=_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError(f"{binary()} could not run: {exc}") from exc


def run(
    git_dir: Path,
    work_tree: Path,
    args: Sequence[str],
    *,
    timeout: float = GIT_TIMEOUT_SECONDS,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run one git command against the store's repository."""
    completed = _invoke(_command(git_dir, work_tree, args), work_tree, timeout)
    if check and completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", "replace").strip()
        raise GitError(f"git {' '.join(args)} failed: {detail or completed.returncode}")
    return completed


def init(git_dir: Path) -> None:
    """Create the store's repository if it is not there yet.

    Bare on purpose: the work tree is a caller argument, never a property of the
    repository, so the workspace can move or be reached under another name without
    the store caring.
    """
    if (git_dir / "HEAD").exists():
        return
    git_dir.parent.mkdir(parents=True, exist_ok=True)
    completed = _invoke(
        [binary(), "init", "--bare", "--quiet", str(git_dir)], None, GIT_TIMEOUT_SECONDS
    )
    if completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", "replace").strip()
        raise GitError(f"git init failed: {detail or completed.returncode}")
