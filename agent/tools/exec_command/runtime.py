"""Running one command: validate, start, wait, render, persist.

Foreground and background share everything up to the point where one waits and the
other hands back a session (ADR 0008: a background command *is* a session, with a
pipe for stdin and a log file for output).
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from agent.tools import process_group, process_store
from agent.tools.exec_command.containment import (
    child_env,
    containment_report,
    decode_capture,
    looks_binary,
)
from agent.tools.exec_command.description import (
    DEFAULT_TIMEOUT_MS,
    MAX_TIMEOUT_MS,
    MIN_TIMEOUT_MS,
)
from agent.tools.exec_command.errors import ExecError
from agent.tools.exec_command.output import foreground_text, persist_and_preview
from agent.tools.output_store import (
    describe_size,
    ensure_dir,
    new_stem,
    output_root,
    preview,
    write_pid_file,
)
from agent.tools.shell_platform import describe_shell, detect_shell
from agent.tools.token_budget import check_text, resolve_max_tokens

TERMINATE_GRACE_SECONDS = 3.0

# Command output is unbounded by nature (unlike a source file), so what goes into
# the event payload is capped and the full text is persisted alongside it.
DETAILS_OUTPUT_CAP_CHARS = 64 * 1024


def normalize_timeout(value: Any) -> int:
    if value is None:
        return DEFAULT_TIMEOUT_MS
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExecError(
            "'timeout' must be a number of milliseconds.",
            reason="invalid_argument",
            argument="timeout",
        )
    return max(MIN_TIMEOUT_MS, min(int(value), MAX_TIMEOUT_MS))


def exec_impl(
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

    timeout_ms = normalize_timeout(timeout)
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

    directory = ensure_dir(
        Path(output_directory) if output_directory else output_root(workspace or None, session_id)
    )
    argv = shell.argv(command)
    env, withheld = child_env()
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
            "containment": containment_report(running, bool(disable_sandbox)),
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
    stdout, stdout_encoding, stdout_replaced = decode_capture(stdout_raw or b"")
    stderr, stderr_encoding, stderr_replaced = decode_capture(stderr_raw or b"")
    running.release()

    duration_ms = int((time.monotonic() - started_at) * 1000)
    binary = looks_binary(stdout_raw or b"") or looks_binary(stderr_raw or b"")
    combined = f"{stdout}\n{stderr}" if (stdout and stderr) else (stdout or stderr)

    persisted_path: Optional[str] = None
    stdout_for_details = stdout
    stderr_for_details = stderr
    truncated = False

    if binary:
        _, persisted_path = persist_and_preview(
            directory, new_stem(), foreground_text(exit_code, stdout, stderr, interrupted, timeout_ms)
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
            model_text = foreground_text(exit_code, stdout, stderr, interrupted, timeout_ms)
        else:
            preview_text, persisted_path = persist_and_preview(
                directory, new_stem(), foreground_text(exit_code, stdout, stderr, interrupted, timeout_ms)
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
        "containment": containment_report(running, bool(disable_sandbox)),
        **shared,
    }
    return model_text, details
