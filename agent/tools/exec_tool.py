"""Run a command in the platform shell, contained as far as the OS allows.

Containment is layered, and the layers are *not* equivalent (see
``docs/decisions/0005-exec-tool.md``):

1. **Process tree + resource caps.** On Windows a Job Object caps process count and
   job memory and terminates the whole tree in one call; on POSIX the command runs
   in its own session and is stopped with ``killpg``. Always on.
2. **Integrity level.** Dropping the command to a low integrity token so it cannot
   write outside what the low integrity SID has been granted. **Not enabled**: the
   token drop itself is verified to work, but on its own it also blocks ordinary
   temp usage, so turning it on needs ACL grants plus a revert path. Recorded in the
   ADR as the next subproject.

What this is **not**: a security boundary. The command can read and write anywhere
the process user can, and ``code_interpreter`` can already do the same, so nothing
here may be described to a user as "sandboxed".

The model gets a readable text rendering (exit code, stdout, stderr, where the full
output went); the UI gets the structured record through an ``exec`` event.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.models import EventCategory, ToolOutcome
from agent.tools import process_group, process_store
from agent.tools.output_store import (
    describe_size,
    ensure_dir,
    new_stem,
    output_root,
    persist_text,
    preview,
    write_pid_file,
)
from agent.tools.shell_platform import (
    FAMILY_CMD,
    FAMILY_POWERSHELL,
    describe_shell,
    detect_shell,
)
from agent.tools.text_encoding import DecodeError, decode_file_bytes, suggest_encodings
from agent.tools.token_budget import check_text, resolve_max_tokens

EXEC_TOOL_NAME = "exec_command"

# ``timeout`` is expressed in milliseconds, matching the tool contract.
DEFAULT_TIMEOUT_MS = 120_000
MIN_TIMEOUT_MS = 1_000
MAX_TIMEOUT_MS = 30 * 60 * 1000

TERMINATE_GRACE_SECONDS = 3.0

# Command output is unbounded by nature (unlike a source file), so what goes into
# the event payload is capped and the full text is persisted alongside it.
DETAILS_OUTPUT_CAP_CHARS = 64 * 1024

INTEGRITY_UNCHANGED = "unchanged"

# Credential-looking environment variables are withheld from commands: defense in
# depth against a build script printing its environment, not a boundary
# (``code_interpreter`` can still read them).
SECRET_ENV_PATTERN = re.compile(r"(API_?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|PASSWD)", re.IGNORECASE)
PASS_SECRET_ENV_FLAG = "EXEC_PASS_SECRET_ENV"


class ExecError(Exception):
    """Raised when the command cannot be started or the arguments are malformed."""

    def __init__(self, message: str, reason: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, "reason": self.reason, **self.details}


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


def _normalize_timeout(value: Any) -> int:
    if value is None:
        return DEFAULT_TIMEOUT_MS
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExecError(
            "'timeout' must be a number of milliseconds.",
            reason="invalid_argument",
            argument="timeout",
        )
    return max(MIN_TIMEOUT_MS, min(int(value), MAX_TIMEOUT_MS))


def _child_env() -> Tuple[Dict[str, str], int]:
    """The environment for the command, with credential-looking names withheld."""
    env = dict(os.environ)
    if (os.getenv(PASS_SECRET_ENV_FLAG) or "").strip() == "1":
        return env, 0
    withheld = 0
    for name in list(env):
        if SECRET_ENV_PATTERN.search(name):
            env.pop(name, None)
            withheld += 1
    return env, withheld


def _decode_capture(raw: bytes) -> Tuple[str, str, bool]:
    """Decode command output, reporting the encoding and whether bytes were lost."""
    if not raw:
        return "", "utf-8", False
    try:
        decoded = decode_file_bytes(raw, "utf-8")
        return decoded.text, decoded.encoding, False
    except DecodeError:
        pass
    for candidate in suggest_encodings(raw):
        name = str(candidate.get("encoding") or "")
        # latin-1 decodes anything, so it would hide a mis-decode behind a
        # plausible looking string. Prefer an explicit replacement marker.
        if not name or name == "latin-1":
            continue
        try:
            return raw.decode(name), name, False
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8", True


def _looks_binary(raw: bytes) -> bool:
    return b"\x00" in raw[:8192]


def _containment(command: process_group.RunningCommand, disable_sandbox: bool) -> Dict[str, Any]:
    """Report what is actually enforcing something, and what is not."""
    return {
        "process_tree": (
            "job-object" if command.kind == process_group.KIND_WINDOWS_JOB else "process-group"
        ),
        "resource_limits": dict(command.limits) or None,
        "integrity_level": INTEGRITY_UNCHANGED,
        "disabled_by_caller": bool(disable_sandbox),
        "note": (
            "Resource limits and process-tree termination only; commands are not confined to the "
            "workspace and this is not a security boundary."
        ),
    }


def _foreground_text(
    exit_code: Optional[int],
    stdout: str,
    stderr: str,
    interrupted: bool,
    timeout_ms: int,
) -> str:
    lines: List[str] = [f"exit_code: {exit_code if exit_code is not None else 'unknown'}"]
    if interrupted:
        lines.append(f"The command was stopped after {timeout_ms} ms and its process tree was terminated.")
    if stdout:
        lines.extend(["--- stdout ---", stdout.rstrip("\n")])
    if stderr:
        lines.extend(["--- stderr ---", stderr.rstrip("\n")])
    if not stdout and not stderr and not interrupted:
        lines.append("(no output)")
    return "\n".join(lines)


def _persist_and_preview(directory: Path, stem: str, text: str) -> Tuple[str, str]:
    """Write the full text to disk and return ``(preview, path)``."""
    path = persist_text(directory, f"{stem}.txt", text)
    return preview(text), path.as_posix()


def _exec_impl(
    command: str,
    timeout: Any,
    description: Any,
    run_in_background: Any,
    disable_sandbox: Any,
    base_dir: Optional[str],
    session_id: str,
    max_tokens: int,
    output_directory: Optional[Path],
    task_id: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """Run the command; return ``(model_text, details)``."""
    if not isinstance(command, str) or not command.strip():
        raise ExecError(
            "'command' must be a non-empty string.", reason="invalid_argument", argument="command"
        )
    if description is not None and not isinstance(description, str):
        raise ExecError(
            "'description' must be a string.", reason="invalid_argument", argument="description"
        )
    for flag, name in (
        (run_in_background, "run_in_background"),
        (disable_sandbox, "dangerouslyDisableSandbox"),
    ):
        if flag is not None and not isinstance(flag, bool):
            raise ExecError(f"'{name}' must be a boolean.", reason="invalid_argument", argument=name)

    timeout_ms = _normalize_timeout(timeout)
    shell = detect_shell()
    if shell is None:
        raise ExecError(
            f"No supported shell was found on this machine ({platform.system()}).",
            reason="no_shell",
            platform=platform.system(),
        )

    workspace = (base_dir or "").strip()
    if workspace and not Path(workspace).is_dir():
        raise ExecError(
            "The workspace root does not exist, so the command has nowhere to start.",
            reason="missing_workspace",
            workspace=workspace,
        )
    cwd = workspace or os.getcwd()

    directory = ensure_dir(Path(output_directory) if output_directory else output_root(workspace or None, session_id))
    argv = shell.argv(command)
    env, withheld = _child_env()
    started_at = time.monotonic()
    shell_text = describe_shell(shell)
    shared: Dict[str, Any] = {
        "command": command,
        "description": description or "",
        "shell": shell_text,
        "shell_family": shell.family,
        "cwd": cwd,
        "withheld_env_vars": withheld,
    }

    if run_in_background:
        stem = new_stem()
        log_path = directory / f"{stem}.log"
        # stdin is a pipe, not DEVNULL: a background command is a session that
        # write_stdin can type into (see docs/decisions/0008-write-stdin-tool.md).
        running = process_group.start_with_log(
            argv, log_path.as_posix(), cwd=cwd, env=env, stdin=subprocess.PIPE
        )
        try:
            session = process_store.register(
                running,
                log_path,
                task_id=task_id,
                workspace=workspace,
                meta={"command": command, "description": description or "", "cwd": cwd},
            )
        except process_store.SessionLimitReached as exc:
            # Refuse rather than kill another session: the model may still be
            # talking to it. The command we just started goes down with the refusal.
            running.kill()
            running.release()
            raise ExecError(
                f"This task already has {exc.limit} background commands running. "
                "Finish one with write_stdin, or stop one, before starting another.",
                reason="too_many_sessions",
                limit=exc.limit,
            ) from exc
        pid_file = write_pid_file(
            directory,
            f"{stem}.pid.json",
            {
                "pid": running.pid,
                "session_id": session.process_id,
                "kind": running.kind,
                "command": command,
                "description": description or "",
                "cwd": cwd,
                "shell": shell_text,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "log": log_path.as_posix(),
            },
        )
        model_text = (
            f"Started in the background (pid {running.pid}, session_id {session.process_id}). "
            f"Output is being written to {log_path.as_posix()}; read it with read_file, or use "
            "write_stdin to type into this session and read what it prints. It is stopped when "
            "the task ends."
        )
        details: Dict[str, Any] = {
            "success": True,
            "background": True,
            "pid": running.pid,
            "session_id": session.process_id,
            "stdout": "",
            "stderr": "",
            "interrupted": False,
            "persistedOutputPath": log_path.as_posix(),
            "pidFile": pid_file.as_posix(),
            "containment": _containment(running, bool(disable_sandbox)),
            "duration_ms": int((time.monotonic() - started_at) * 1000),
            **shared,
        }
        return model_text, details

    running = process_group.start(argv, cwd=cwd, env=env)
    interrupted = False
    try:
        stdout_raw, stderr_raw = running.process.communicate(timeout=timeout_ms / 1000)
    except subprocess.TimeoutExpired:
        interrupted = True
        running.stop()
        try:
            stdout_raw, stderr_raw = running.process.communicate(timeout=TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            running.kill()
            try:
                stdout_raw, stderr_raw = running.process.communicate(timeout=TERMINATE_GRACE_SECONDS)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                stdout_raw, stderr_raw = b"", b""

    exit_code = running.process.returncode
    stdout, stdout_encoding, stdout_replaced = _decode_capture(stdout_raw or b"")
    stderr, stderr_encoding, stderr_replaced = _decode_capture(stderr_raw or b"")
    running.release()

    duration_ms = int((time.monotonic() - started_at) * 1000)
    binary = _looks_binary(stdout_raw or b"") or _looks_binary(stderr_raw or b"")
    combined = f"{stdout}\n{stderr}" if (stdout and stderr) else (stdout or stderr)

    persisted_path: Optional[str] = None
    stdout_for_details = stdout
    stderr_for_details = stderr
    truncated = False

    if binary:
        _, persisted_path = _persist_and_preview(
            directory, new_stem(), _foreground_text(exit_code, stdout, stderr, interrupted, timeout_ms)
        )
        model_text = (
            f"exit_code: {exit_code if exit_code is not None else 'unknown'}\n"
            f"The command produced binary output ({len(stdout_raw or b'')} bytes on stdout), so it "
            f"was written to {persisted_path} instead of being inlined."
        )
        if interrupted:
            model_text = f"The command was stopped after {timeout_ms} ms.\n{model_text}"
        stdout_for_details, stderr_for_details = "", ""
        truncated = True
    else:
        budget_report = check_text(combined, resolve_max_tokens(max_tokens))
        if budget_report.ok:
            model_text = _foreground_text(exit_code, stdout, stderr, interrupted, timeout_ms)
        else:
            preview_text, persisted_path = _persist_and_preview(
                directory, new_stem(), _foreground_text(exit_code, stdout, stderr, interrupted, timeout_ms)
            )
            model_text = (
                f"exit_code: {exit_code if exit_code is not None else 'unknown'}\n"
                f"The output was too large to return ({describe_size(combined)['bytes']} bytes); the "
                f"full text is at {persisted_path}. Read it in slices with read_file (offset/limit).\n"
                f"--- preview ---\n{preview_text}"
            )
            stdout_for_details = preview(stdout)
            stderr_for_details = preview(stderr)
            truncated = True

    # The event payload is capped separately: command output can be arbitrarily large.
    if len(stdout_for_details) > DETAILS_OUTPUT_CAP_CHARS:
        stdout_for_details = stdout_for_details[:DETAILS_OUTPUT_CAP_CHARS]
        truncated = True
    if len(stderr_for_details) > DETAILS_OUTPUT_CAP_CHARS:
        stderr_for_details = stderr_for_details[:DETAILS_OUTPUT_CAP_CHARS]
        truncated = True

    details = {
        "success": True,
        "background": False,
        "exit_code": exit_code,
        "stdout": stdout_for_details,
        "stderr": stderr_for_details,
        "interrupted": interrupted,
        "persistedOutputPath": persisted_path,
        "output_truncated": truncated,
        "output_encoding": stdout_encoding if stdout_encoding != "utf-8" else stderr_encoding,
        "output_decoded_with_replacements": stdout_replaced or stderr_replaced,
        "output_binary": binary,
        "output_size": describe_size(combined),
        "duration_ms": duration_ms,
        "containment": _containment(running, bool(disable_sandbox)),
        **shared,
    }
    return model_text, details


def list_background() -> List[Dict[str, Any]]:
    """Background commands this process started and still holds handles for."""
    return [
        {
            "pid": session.pid,
            "session_id": session.process_id,
            "kind": session.command.kind,
            "running": session.running(),
        }
        for session in process_store.list_sessions()
    ]


def stop_background(pid: int) -> bool:
    """Stop a background command and its tree; ``False`` when the pid is unknown."""
    session = process_store.find_by_pid(pid)
    if session is None:
        return False
    command = session.command
    command.stop()
    try:
        # Give the tree a moment to actually go away, so the caller is not left
        # holding a process that is merely "being" killed.
        command.process.wait(timeout=TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        command.kill()
    process_store.retire(session)
    return True


def make_exec_tool(
    base_dir: Optional[str],
    session_id: str = "",
    max_tokens: int = 0,
    output_directory: Optional[Path] = None,
    task_id: str = "",
):
    """Bind the exec_command tool to a workspace root and an output directory."""

    def exec_command(
        command: Any = None,
        timeout: Any = None,
        description: Any = None,
        run_in_background: Any = None,
        dangerouslyDisableSandbox: Any = None,
    ) -> ToolOutcome:
        try:
            model_text, details = _exec_impl(
                command,
                timeout,
                description,
                run_in_background,
                dangerouslyDisableSandbox,
                base_dir,
                session_id,
                max_tokens,
                output_directory,
                task_id,
            )
        except ExecError as exc:
            payload = exc.to_dict()
            return ToolOutcome(
                model_text=f"Error: {exc.message}",
                event_category=EventCategory.EXEC,
                event_title=f"Command rejected: {(command or '').strip()[:60]}",
                details={"success": False, **payload},
            )

        headline = (command or "").strip().splitlines()
        title_source = headline[0] if headline else ""
        if details.get("description"):
            title_source = details["description"]
        return ToolOutcome(
            model_text=model_text,
            event_category=EventCategory.EXEC,
            event_title=f"Command: {title_source[:60]}",
            details=details,
        )

    return exec_command
