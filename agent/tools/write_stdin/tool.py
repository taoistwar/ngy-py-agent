"""The ``write_stdin`` call itself: look up, type, listen, report.

Ownership is checked here rather than inside the helpers: a session belongs to the
task and workspace that started it, so a foreign id is answered exactly like an
unknown one.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from agent.models import EventCategory, ToolOutcome
from agent.tools import process_group, process_store
from agent.tools.write_stdin.errors import WriteStdinError
from agent.tools.write_stdin.render import fit_output, render
from agent.tools.write_stdin.rules import CTRL_C, as_chars, effective_yield_ms, output_budget
from agent.tools.write_stdin.session_io import collect_output, write_to_session


def write_stdin_impl(
    session_id: Any,
    chars: Any,
    yield_time_ms: Any,
    max_output_tokens: Any,
    configured_max_tokens: int,
    task_id: str,
    workspace: str,
    output_directory: Optional[Path],
) -> Tuple[str, Dict[str, Any]]:
    """Answer one ``write_stdin`` call; return ``(model_text, details)``."""
    if not isinstance(session_id, str) or not session_id.strip():
        raise WriteStdinError(
            "'session_id' must be the non-empty id exec_command returned.",
            reason="invalid_argument",
            argument="session_id",
        )
    session_id = session_id.strip()
    typed = as_chars(chars)

    # ``session_id`` is a capability: a session owned by another task or workspace
    # is answered exactly like an unknown one, so a probe learns nothing.
    session = process_store.get(session_id, task_id=task_id, workspace=workspace)
    if session is None:
        raise WriteStdinError(
            f"Unknown session {session_id!r}: it may have already exited. "
            "Start the command again with exec_command to get a new session_id.",
            reason="unknown_session",
            session_id=session_id,
        )

    interrupt = typed == CTRL_C
    if interrupt:
        # Ctrl-C is not input: it asks the command to stop and forces it if it
        # refuses to go.
        process_group.interrupt(session.command)
    elif typed:
        write_to_session(session, typed)

    wait_ms = effective_yield_ms(yield_time_ms, is_write=bool(typed) and not interrupt)
    started = time.monotonic()
    output = collect_output(session, wait_ms)
    wall_seconds = time.monotonic() - started

    exit_code = session.command.poll()
    running = exit_code is None
    budget = output_budget(max_output_tokens, configured_max_tokens)
    rendered, tokens, truncated, persisted = fit_output(output, budget, output_directory)

    if not running:
        # The command is gone; release its handles and forget the session.
        process_store.retire(session)

    return render(
        session,
        rendered,
        tokens,
        truncated,
        persisted,
        running,
        exit_code,
        wall_seconds,
        typed,
        wait_ms,
    )


def make_write_stdin_tool(
    max_tokens: int = 0,
    task_id: str = "",
    workspace: str = "",
    output_directory: Optional[Path] = None,
):
    """Bind ``write_stdin`` to the process store, the run's budget and its workspace.

    ``task_id``/``workspace`` are the ownership half of the contract: they decide
    which sessions this tool is allowed to see at all.
    """

    def write_stdin(
        session_id: Any = None,
        chars: Any = None,
        yield_time_ms: Any = None,
        max_output_tokens: Any = None,
    ) -> ToolOutcome:
        try:
            model_text, details = write_stdin_impl(
                session_id,
                chars,
                yield_time_ms,
                max_output_tokens,
                max_tokens,
                task_id,
                workspace,
                output_directory,
            )
        except WriteStdinError as exc:
            return ToolOutcome(
                model_text=f"Error: {exc.message}",
                event_category=EventCategory.EXEC,
                event_title="write_stdin rejected",
                details={"success": False, **exc.to_dict()},
            )

        return ToolOutcome(
            model_text=model_text,
            event_category=EventCategory.EXEC,
            event_title=f"Session {details.get('session_id') or 'exited'}",
            details=details,
        )

    return write_stdin
