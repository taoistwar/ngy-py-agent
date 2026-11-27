"""The ``exec_command`` factory and the background-session helpers.

``list_background``/``stop_background`` are the in-process view of the sessions
``run_in_background`` leaves behind; the task-scoped reaping lives in
``agent.agent_loop`` (ADR 0008).

A background start is also recorded in the run's ledger
(:mod:`agent.tools.background`), which is how the model is told the command ended
instead of having to poll for it (ADR 0034).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agent.models import EventCategory, ToolOutcome
from agent.tools import process_store
from agent.tools.background import BackgroundTasks
from agent.tools.exec_command.description import EXEC_TOOL_NAME
from agent.tools.exec_command.errors import ExecError
from agent.tools.exec_command.runtime import TERMINATE_GRACE_SECONDS, exec_impl


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
    should_stop: Optional[Callable[[], bool]] = None,
    background: Optional[BackgroundTasks] = None,
):
    """Bind the exec_command tool to a workspace root and an output directory."""

    def exec_command(
        command: Any = None,
        timeout: Any = None,
        description: Any = None,
        run_in_background: Any = None,
        tty: Any = None,
        dangerouslyDisableSandbox: Any = None,
    ) -> ToolOutcome:
        try:
            model_text, details = exec_impl(
                command,
                timeout,
                description,
                run_in_background,
                tty,
                dangerouslyDisableSandbox,
                base_dir,
                session_id,
                max_tokens,
                output_directory,
                task_id,
                should_stop=should_stop,
            )
        except ExecError as exc:
            payload = exc.to_dict()
            return ToolOutcome(
                model_text=f"Error: {exc.message}",
                event_category=EventCategory.EXEC,
                event_title=f"Command rejected: {(command or '').strip()[:60]}",
                details={"success": False, **payload},
            )

        if background is not None and details.get("background"):
            # Recorded after a successful start only: a refused background command
            # (session limit, no shell) has nothing to report later.
            background.track(
                session_id=str(details.get("session_id") or ""),
                pid=int(details.get("pid") or 0),
                command=str(command or ""),
                description=str(details.get("description") or ""),
                log_path=str(details.get("persistedOutputPath") or ""),
                tty=bool(details.get("tty")),
            )

        headline = (command or "").strip().splitlines()
        title_source = headline[0] if headline else ""
        if details.get("description"):
            title_source = details["description"]
        return ToolOutcome(
            model_text=model_text,
            event_category=EventCategory.EXEC,
            event_title=f"{EXEC_TOOL_NAME} : {title_source[:60]}",
            details=details,
        )

    return exec_command
