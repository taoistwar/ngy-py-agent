"""What the model is told about ``exec_command``: its name, description and schema.

The description is written for the shell this machine actually has, so the model is
told which dialect to write in (see ``docs/decisions/0005-exec-tool.md``).
"""

from __future__ import annotations

import platform
from typing import Any, Dict, Optional

from agent.tools.shell_platform import (
    FAMILY_CMD,
    FAMILY_POWERSHELL,
    detect_shell,
)

EXEC_TOOL_NAME = "exec_command"

# ``timeout`` is expressed in milliseconds, matching the tool contract.
DEFAULT_TIMEOUT_MS = 120_000
MIN_TIMEOUT_MS = 1_000
MAX_TIMEOUT_MS = 30 * 60 * 1000


def _dialect_hint(shell: Any) -> str:
    # Name the concrete shell (bash/zsh/sh, not a generic "zsh/bash") so the model
    # is not asked to split attention across dialects it will never see.
    if shell.family == FAMILY_POWERSHELL:
        return (
            "The command runs in PowerShell 7+, so write PowerShell syntax: '$env:NAME' for "
            "environment variables, ';' to chain statements, and 'cmd /c' for cmd-only builtins."
        )
    if shell.family == FAMILY_CMD:
        return (
            "The command runs in cmd.exe, so write cmd syntax: '%NAME%' for environment "
            "variables, '&&' to chain, and avoid PowerShell cmdlets."
        )
    return (
        f"The command runs in {shell.display}, a POSIX shell, so write POSIX syntax: '$NAME' for "
        "environment variables, '&&' to chain, and POSIX utilities."
    )


def build_exec_description(shell: Optional[Any] = None) -> str:
    """The model-facing description, written for the shell this machine has."""
    if shell is None:
        shell = detect_shell()
    if shell is None:
        return (
            "Run a shell command. No supported shell was found on this machine "
            f"({platform.system()}), so every call will fail."
        )
    return (
        f"Run a shell command and return its output. {_dialect_hint(shell)} "
        "The command starts in the workspace root. This tool does not confine paths: the command "
        "can read and write anywhere the process user can, so keep paths inside the workspace and "
        "use read_file/edit_file/write_file for project files. 'timeout' is in MILLISECONDS "
        "(default 120000, maximum 1800000); when it fires the whole process tree is stopped and "
        "'interrupted' is true. Output above the response budget is written to a file and the "
        "result carries a short preview plus that path, which read_file can read back. "
        "'run_in_background' starts the command without waiting and returns its pid, a session_id "
        "and the log path; feed that session_id to write_stdin to type into it and read its output. "
        "The command keeps running until it exits or the task ends, when it is stopped. Give a short "
        "'description' of what the command "
        "does: the user is shown it when confirming the command, and it is recorded for the audit "
        "trail. "
        "'dangerouslyDisableSandbox' only skips the extra containment layer (integrity level); "
        "resource limits and process-tree termination always stay on."
    )


EXEC_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "The command line to run in this platform's shell.",
        },
        "timeout": {
            "type": "integer",
            "minimum": MIN_TIMEOUT_MS,
            "maximum": MAX_TIMEOUT_MS,
            "description": (
                "Timeout in MILLISECONDS. Defaults to 120000 (2 minutes); the maximum is 1800000 "
                "(30 minutes). On timeout the process tree is stopped and 'interrupted' is true."
            ),
        },
        "description": {
            "type": "string",
            "description": (
                "A short, plain-language summary of what the command does, written for a human "
                "deciding whether to allow it (for example 'Install lodash utility library'). It "
                "is shown in the confirmation prompt before the command runs and recorded for "
                "the audit trail."
            ),
        },
        "run_in_background": {
            "type": "boolean",
            "description": (
                "Start the command and return immediately instead of waiting. The result carries "
                "the pid, a session_id (pass it to write_stdin to interact) and the log path. The "
                "command is stopped when the task ends. Defaults to false."
            ),
        },
        "dangerouslyDisableSandbox": {
            "type": "boolean",
            "description": (
                "Skip the additional containment layer (integrity level) for this command. "
                "Resource limits and process-tree termination cannot be disabled. Defaults to false."
            ),
        },
    },
    "required": ["command"],
}
