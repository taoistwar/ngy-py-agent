"""Which shell ``exec_command`` runs, and how the command string reaches it.

The model has to write commands in a concrete dialect (``$env:FOO`` is not
``$FOO``), so the chosen shell is part of the tool contract: it is named in the
tool description and reported again in every result.

Candidate order per platform, first hit wins:

- Windows: ``pwsh`` (PowerShell 7+) -> Windows PowerShell -> ``cmd``.
- macOS: ``zsh`` -> ``bash`` -> ``sh``.
- Linux/other POSIX: ``bash`` -> ``sh``.

Two deliberate exclusions on Windows:

- ``bash`` is the **WSL launcher**. It would run the command inside a different
  filesystem, so the same path silently means a different file - the hardest kind
  of bug to diagnose. It is never selected, even when it is the only "bash".
- MSYS/Git ``sh`` is excluded for the same reason (mixed path translation).

See ``docs/decisions/0005-exec-tool.md``.
"""

from __future__ import annotations

import functools
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

WINDOWS = "Windows"
MACOS = "Darwin"
LINUX = "Linux"

VERSION_PROBE_TIMEOUT_SECONDS = 5

FAMILY_POWERSHELL = "powershell"
FAMILY_POSIX = "posix"
FAMILY_CMD = "cmd"


@dataclass(frozen=True)
class Shell:
    """A concrete shell that ``exec_command`` can drive."""

    family: str
    executable: str
    display: str
    platform_name: str = field(default="")

    def argv(self, command: str) -> List[str]:
        """Build the argv that runs ``command`` in this shell."""
        if self.family == FAMILY_POWERSHELL:
            return [self.executable, "-NoProfile", "-NonInteractive", "-Command", command]
        if self.family == FAMILY_CMD:
            return [self.executable, "/d", "/s", "/c", command]
        return [self.executable, "-c", command]

    @property
    def is_posix(self) -> bool:
        return self.family == FAMILY_POSIX


def _first_available(candidates: Tuple[Tuple[str, str, str], ...]) -> Optional[Shell]:
    """Return the first candidate that resolves on PATH.

    Each candidate is ``(family, executable_or_name, display)``.
    """
    for family, candidate, display in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return Shell(family=family, executable=resolved, display=display)
    return None


def _system_root_shell(*parts: str) -> Optional[str]:
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    path = os.path.join(root, *parts)
    return path if os.path.exists(path) else None


def _windows_candidates() -> Tuple[Tuple[str, str, str], ...]:
    legacy = _system_root_shell("System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    comspec = os.environ.get("COMSPEC") or "cmd.exe"
    candidates = [
        (FAMILY_POWERSHELL, "pwsh", "pwsh (PowerShell 7+)"),
    ]
    if legacy:
        candidates.append((FAMILY_POWERSHELL, legacy, "Windows PowerShell (5.1)"))
    candidates.append((FAMILY_CMD, comspec, "cmd.exe"))
    return tuple(candidates)


def _posix_candidates(system: str) -> Tuple[Tuple[str, str, str], ...]:
    if system == MACOS:
        return (
            (FAMILY_POSIX, "zsh", "zsh"),
            (FAMILY_POSIX, "bash", "bash"),
            (FAMILY_POSIX, "/bin/sh", "sh"),
        )
    return (
        (FAMILY_POSIX, "bash", "bash"),
        (FAMILY_POSIX, "/bin/sh", "sh"),
    )


@functools.lru_cache(maxsize=4)
def detect_shell() -> Optional[Shell]:
    """The shell ``exec_command`` will use on this machine, or ``None`` when there is none."""
    system = platform.system()
    if system == WINDOWS:
        return _first_available(_windows_candidates())
    if system in (MACOS, LINUX):
        return _first_available(_posix_candidates(system))
    return _first_available(_posix_candidates(LINUX))


@functools.lru_cache(maxsize=4)
def probe_shell_version(executable: str, family: str) -> str:
    """Best-effort version string, probed once per shell and never fatal."""
    if family == FAMILY_POWERSHELL:
        argv = [executable, "-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.ToString()"]
    elif family == FAMILY_POSIX:
        argv = [executable, "--version"]
    else:
        return ""
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=VERSION_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    output = (completed.stdout or completed.stderr or "").strip()
    if not output:
        return ""
    first_line = output.splitlines()[0].strip()
    return first_line[:120]


def describe_shell(shell: Optional[Shell]) -> str:
    """Human readable shell identity, version included when it is known."""
    if shell is None:
        return "no supported shell found"
    version = probe_shell_version(shell.executable, shell.family)
    return f"{shell.display} at {shell.executable}" + (f" (version {version})" if version else "")
